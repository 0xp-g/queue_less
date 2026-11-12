"""All SQL touching tickets (Repository pattern).

The two concurrency-critical statements live here and only here (ADR-0002):
  * join_ticket(): queue-row lock serializes seq assignment per queue; idempotent on retry
  * call_next():   FOR UPDATE SKIP LOCKED - two counters never get the same ticket
Every other status change is a compare-and-set (ADR-0003).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ticket


@dataclass(frozen=True)
class JoinResult:
    ticket_id: int
    seq: int
    version: int


@dataclass(frozen=True)
class CallResult:
    ticket_id: int
    seq: int


_JOIN_SQL = text(
    """
    WITH s AS (
        UPDATE queues SET next_seq = next_seq + 1, version = version + 1
        WHERE id = :qid AND status = 'open'
        RETURNING next_seq, version
    )
    INSERT INTO tickets (queue_id, seq, client_request_id, device_id, token_hash)
    SELECT :qid, s.next_seq, :rid, :dev, :hash FROM s
    ON CONFLICT (queue_id, client_request_id) DO NOTHING
    RETURNING id, seq, (SELECT version FROM s) AS version
    """
)

_CALL_NEXT_SQL = text(
    """
    WITH n AS (
        SELECT id FROM tickets
        WHERE queue_id = :qid AND status = 'waiting'
        ORDER BY seq
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE tickets t
       SET status = 'called', called_at = now(), counter_id = :cid
      FROM n
     WHERE t.id = n.id
    RETURNING t.id, t.seq
    """
)

_SWEEP_SQL = text(
    """
    UPDATE tickets t
       SET status = 'no_show', closed_at = now()
      FROM queues q
     WHERE t.queue_id = q.id
       AND t.status = 'called'
       AND t.called_at < now() - make_interval(secs => q.no_show_grace_sec)
    RETURNING t.id, t.queue_id
    """
)

# One ranked query per queue per event per API instance: positions for the connected tickets.
_POSITIONS_SQL = text(
    """
    WITH w AS (
        SELECT id, row_number() OVER (ORDER BY seq) AS position
        FROM tickets
        WHERE queue_id = :qid AND status = 'waiting'
    )
    SELECT t.id, t.seq, t.status, w.position, c.label AS counter
    FROM tickets t
    LEFT JOIN w ON w.id = t.id
    LEFT JOIN counters c ON c.id = t.counter_id
    WHERE t.id = ANY(:ids)
    """
)


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    # --- reads -------------------------------------------------------------------------------
    async def get(self, ticket_id: int) -> Ticket | None:
        return await self._s.get(Ticket, ticket_id, populate_existing=True)

    async def get_by_token_hash(self, token_hash: str) -> Ticket | None:
        return await self._s.scalar(select(Ticket).where(Ticket.token_hash == token_hash))

    async def get_by_request(self, queue_id: int, client_request_id: str) -> Ticket | None:
        return await self._s.scalar(
            select(Ticket).where(
                Ticket.queue_id == queue_id, Ticket.client_request_id == client_request_id
            )
        )

    async def active_for_device(self, queue_id: int, device_id: str) -> Ticket | None:
        return await self._s.scalar(
            select(Ticket).where(
                Ticket.queue_id == queue_id,
                Ticket.device_id == device_id,
                Ticket.status.in_(("waiting", "called", "serving")),
            )
        )

    async def position(self, ticket: Ticket) -> int | None:
        """position = waiting tickets ahead + 1, computed and never stored (ADR-0001)."""
        if ticket.status != "waiting":
            return None
        ahead = await self._s.scalar(
            text(
                "SELECT count(*) FROM tickets "
                "WHERE queue_id = :qid AND status = 'waiting' AND seq < :seq"
            ),
            {"qid": ticket.queue_id, "seq": ticket.seq},
        )
        return ahead + 1

    async def positions_for(self, queue_id: int, ticket_ids: list[int]) -> dict[int, dict]:
        if not ticket_ids:
            return {}
        rows = await self._s.execute(_POSITIONS_SQL, {"qid": queue_id, "ids": ticket_ids})
        return {r["id"]: dict(r) for r in rows.mappings()}

    async def list_for_queue(
        self, queue_id: int, statuses: tuple[str, ...], limit: int = 200
    ) -> list[Ticket]:
        rows = await self._s.scalars(
            select(Ticket)
            .where(Ticket.queue_id == queue_id, Ticket.status.in_(statuses))
            .order_by(Ticket.seq)
            .limit(limit)
        )
        return list(rows)

    async def wait_samples(self, queue_id: int) -> list[dict]:
        """Every ticket that has been called: ETA at join vs the actual wait (ADR-0007)."""
        rows = await self._s.execute(
            text(
                """
                SELECT status, eta_at_join_sec,
                       extract(epoch FROM called_at - joined_at) AS waited_sec
                FROM tickets
                WHERE queue_id = :qid AND called_at IS NOT NULL
                """
            ),
            {"qid": queue_id},
        )
        return [dict(r) for r in rows.mappings()]

    async def status_counts(self, queue_id: int) -> dict[str, int]:
        rows = await self._s.execute(
            text("SELECT status, count(*) FROM tickets WHERE queue_id = :qid GROUP BY status"),
            {"qid": queue_id},
        )
        return {status: n for status, n in rows}

    # --- concurrency-critical writes ---------------------------------------------------------
    async def join_ticket(
        self, queue_id: int, client_request_id: str, device_id: str | None, token_hash: str
    ) -> JoinResult | None:
        """Assign the next seq atomically. None means: queue not open, or an idempotent replay."""
        row = (
            await self._s.execute(
                _JOIN_SQL,
                {"qid": queue_id, "rid": client_request_id, "dev": device_id, "hash": token_hash},
            )
        ).first()
        return JoinResult(row.id, row.seq, row.version) if row else None

    async def call_next(self, queue_id: int, counter_id: int | None) -> CallResult | None:
        row = (await self._s.execute(_CALL_NEXT_SQL, {"qid": queue_id, "cid": counter_id})).first()
        return CallResult(row.id, row.seq) if row else None

    async def transition(
        self, ticket_id: int, expected: str, new_status: str, **fields: datetime | int | None
    ) -> bool:
        """Compare-and-set: succeeds only if nobody changed the status since we read it."""
        result = await self._s.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id, Ticket.status == expected)
            .values(status=new_status, **fields)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    async def set_eta_at_join(self, ticket_id: int, eta_sec: float) -> None:
        await self._s.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(eta_at_join_sec=eta_sec)
            .execution_options(synchronize_session=False)
        )

    async def move_to_back(self, ticket_id: int, new_seq: int) -> None:
        """Requeue: a fresh seq puts the ticket at the back without touching anyone else."""
        await self._s.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(
                seq=new_seq,
                requeue_count=Ticket.requeue_count + 1,
                called_at=None,
                counter_id=None,
                closed_at=None,
            )
            .execution_options(synchronize_session=False)
        )

    async def sweep_no_shows(self) -> list[tuple[int, int]]:
        """Idempotent: safe to run on every API instance concurrently (ADR-0008)."""
        rows = await self._s.execute(_SWEEP_SQL)
        return [(r.id, r.queue_id) for r in rows]
