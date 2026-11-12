"""All SQL touching queues and counters (Repository pattern)."""

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Counter, Queue, Ticket


class QueueRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def get(self, queue_id: int) -> Queue | None:
        return await self._s.get(Queue, queue_id)

    async def get_for_venue(self, queue_id: int, venue_id: int) -> Queue | None:
        """Tenant-scoped lookup: a queue in another venue looks like it does not exist."""
        queue = await self._s.get(Queue, queue_id)
        return queue if queue is not None and queue.venue_id == venue_id else None

    async def list_for_venue(self, venue_id: int) -> list[Queue]:
        rows = await self._s.scalars(
            select(Queue).where(Queue.venue_id == venue_id).order_by(Queue.id)
        )
        return list(rows)

    def add(self, obj: Queue | Counter) -> None:
        self._s.add(obj)

    async def flush(self) -> None:
        await self._s.flush()

    async def lock(self, queue_id: int) -> Queue | None:
        """SELECT ... FOR UPDATE on the queue row.

        Lock ordering rule (deadlock avoidance): a transaction that touches both a ticket and
        its queue locks the ticket first, then the queue. Join only locks the queue row.
        """
        return await self._s.scalar(
            select(Queue)
            .where(Queue.id == queue_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def bump_version(self, queue_id: int) -> int:
        """Increment the per-queue event version inside the current transaction (ADR-0005)."""
        return await self._s.scalar(
            update(Queue)
            .where(Queue.id == queue_id)
            .values(version=Queue.version + 1)
            .returning(Queue.version)
        )

    async def counters(self, queue_id: int) -> list[Counter]:
        rows = await self._s.scalars(
            select(Counter).where(Counter.queue_id == queue_id).order_by(Counter.id)
        )
        return list(rows)

    async def get_counter(self, counter_id: int) -> Counter | None:
        return await self._s.get(Counter, counter_id)

    async def active_counter_count(self, queue_id: int) -> int:
        return await self._s.scalar(
            select(func.count())
            .select_from(Counter)
            .where(Counter.queue_id == queue_id, Counter.active.is_(True))
        )

    async def header(self, queue_id: int) -> dict | None:
        """Everything a snapshot needs about the queue, in one round trip."""
        row = (
            (
                await self._s.execute(
                    text(
                        """
                    SELECT q.id, q.name, q.status, q.version, q.default_service_sec,
                           q.est_service_sec,
                           (SELECT count(*) FROM counters c
                             WHERE c.queue_id = q.id AND c.active) AS active_counters,
                           (SELECT count(*) FROM tickets t
                             WHERE t.queue_id = q.id AND t.status = 'waiting') AS waiting,
                           (SELECT count(*) FROM tickets t
                             WHERE t.queue_id = q.id
                               AND t.status IN ('called', 'serving')) AS busy,
                           (SELECT max(t.seq) FROM tickets t
                             WHERE t.queue_id = q.id AND t.called_at IS NOT NULL) AS now_serving
                    FROM queues q WHERE q.id = :qid
                    """
                    ),
                    {"qid": queue_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def serving_by_counter(self, queue_id: int) -> list[dict]:
        """Display board: the ticket each counter is currently handling."""
        rows = await self._s.execute(
            select(Counter.id, Counter.label, Ticket.seq, Ticket.status)
            .outerjoin(
                Ticket,
                (Ticket.counter_id == Counter.id) & (Ticket.status.in_(("called", "serving"))),
            )
            .where(Counter.queue_id == queue_id)
            .order_by(Counter.id, Ticket.seq.desc())
        )
        seen: dict[int, dict] = {}
        for cid, label, seq, status in rows:
            seen.setdefault(cid, {"counter_id": cid, "label": label, "seq": seq, "status": status})
        return list(seen.values())
