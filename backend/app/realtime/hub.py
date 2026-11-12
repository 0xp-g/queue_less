"""Per-instance WebSocket registry and fan-out (Observer pattern, ADR-0005).

On every queue event, this instance runs ONE ranked query for that queue and pushes each
connected visitor their own {now_serving, position, eta_seconds, version}. Bursts are coalesced:
if events arrive while a refresh for the same queue is running, one more refresh runs afterwards
instead of one per event.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.domain.events import DomainEvent
from app.services.snapshot_service import SnapshotService
from app.services.unit_of_work import UowFactory

log = logging.getLogger(__name__)


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    queue_id: int
    ticket_id: int | None = None  # None: display board / staff console
    alive: bool = field(default=True)

    async def send(self, payload: dict, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self.ws.send_json(payload), timeout)
            return True
        except Exception:  # slow or dead socket: drop it, the client reconnects + resyncs
            self.alive = False
            return False


class ConnectionManager:
    def __init__(self, uow: UowFactory, snapshots: SnapshotService, send_timeout: float = 2.0):
        self._uow = uow
        self._snapshots = snapshots
        self._send_timeout = send_timeout
        self._conns: dict[int, set[Connection]] = {}
        self._dirty: dict[int, str] = {}  # queue_id -> latest event type awaiting refresh
        self._running: set[int] = set()
        self._tasks: set[asyncio.Task] = set()

    # --- registry ----------------------------------------------------------------------------
    async def connect(self, conn: Connection) -> None:
        self._conns.setdefault(conn.queue_id, set()).add(conn)
        await self.send_snapshot(conn)  # a late or reconnecting client is never stale

    def disconnect(self, conn: Connection) -> None:
        conns = self._conns.get(conn.queue_id)
        if conns is not None:
            conns.discard(conn)
            if not conns:
                del self._conns[conn.queue_id]

    def connection_count(self, queue_id: int | None = None) -> int:
        if queue_id is not None:
            return len(self._conns.get(queue_id, ()))
        return sum(len(c) for c in self._conns.values())

    # --- outbound ----------------------------------------------------------------------------
    async def send_snapshot(self, conn: Connection) -> None:
        payloads = await self._build(conn.queue_id, [conn], "snapshot", None)
        if payloads:
            await conn.send(payloads[conn], self._send_timeout)

    async def on_event(self, event: DomainEvent) -> None:
        """Called by the Redis listener (or the in-memory publisher). Never blocks the caller."""
        if event.queue_id not in self._conns:
            return
        self._dirty[event.queue_id] = event.type
        if event.queue_id in self._running:
            return  # the running refresh loop will pick this up (coalescing)
        task = asyncio.create_task(self._refresh_loop(event.queue_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def resync_all(self) -> None:
        """After a Redis reconnect we may have missed events: push fresh state everywhere."""
        for queue_id in list(self._conns):
            await self.on_event(DomainEvent(queue_id, "resync", 0))

    async def _refresh_loop(self, queue_id: int) -> None:
        self._running.add(queue_id)
        try:
            while queue_id in self._dirty:
                event_type = self._dirty.pop(queue_id)
                conns = list(self._conns.get(queue_id, ()))
                if not conns:
                    continue
                try:
                    payloads = await self._build(queue_id, conns, "update", event_type)
                except Exception:
                    log.exception("refresh failed for queue %s", queue_id)
                    continue
                results = await asyncio.gather(
                    *(c.send(p, self._send_timeout) for c, p in payloads.items())
                )
                for conn, ok in zip(payloads, results, strict=True):
                    if not ok:
                        self.disconnect(conn)
        finally:
            self._running.discard(queue_id)

    async def _build(
        self, queue_id: int, conns: list[Connection], msg_type: str, event_type: str | None
    ) -> dict[Connection, dict]:
        ticket_ids = [c.ticket_id for c in conns if c.ticket_id is not None]
        async with self._uow() as uow:
            header, views = await self._snapshots.for_tickets(uow, queue_id, ticket_ids)
            board = None
            if any(c.ticket_id is None for c in conns):
                board = await self._snapshots.board(uow, queue_id)
        if header is None:
            return {}
        out: dict[Connection, dict] = {}
        for conn in conns:
            view = board if conn.ticket_id is None else views.get(conn.ticket_id)
            if view is None:
                continue
            out[conn] = {"type": msg_type, "event": event_type, **view}
        return out
