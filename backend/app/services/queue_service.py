"""Admin and public queue use cases: create, update status, QR codes, board, stats."""

import statistics
import time
from datetime import date

from app.core.errors import Forbidden, NotFound
from app.core.qr import qr_png_base64
from app.db.models import Counter, Queue, StaffUser
from app.domain.events import QueueEventType
from app.domain.tokens import CounterNonceService, JoinTokenService
from app.services.snapshot_service import SnapshotService
from app.services.staff_service import actor
from app.services.unit_of_work import UnitOfWork, UowFactory


def _require_admin(staff: StaffUser) -> None:
    if staff.role != "admin":  # defence in depth; routes also declare require_role("admin")
        raise Forbidden("Admin role required.")


def queue_dict(q: Queue, counters: list[Counter]) -> dict:
    return {
        "id": q.id,
        "name": q.name,
        "status": q.status,
        "version": q.version,
        "default_service_sec": q.default_service_sec,
        "est_service_sec": q.est_service_sec,
        "no_show_grace_sec": q.no_show_grace_sec,
        "max_requeues": q.max_requeues,
        "counters": [{"id": c.id, "label": c.label, "active": c.active} for c in counters],
    }


class QueueService:
    def __init__(
        self,
        uow: UowFactory,
        join_tokens: JoinTokenService,
        counter_nonces: CounterNonceService,
        snapshots: SnapshotService,
        public_base_url: str,
        eta_error_min_wait_sec: float,
        today=date.today,
        clock=time.time,
    ):
        self._uow = uow
        self._join_tokens = join_tokens
        self._nonces = counter_nonces
        self._snapshots = snapshots
        self._base = public_base_url.rstrip("/")
        self._min_wait = eta_error_min_wait_sec
        self._today = today
        self._clock = clock

    async def _queue(self, uow: UnitOfWork, staff: StaffUser, queue_id: int) -> Queue:
        queue = await uow.queues.get_for_venue(queue_id, staff.venue_id)
        if queue is None:
            raise NotFound("Queue not found.")
        return queue

    async def create(
        self,
        staff: StaffUser,
        name: str,
        counters: int,
        default_service_sec: float,
        no_show_grace_sec: int,
        max_requeues: int,
    ) -> dict:
        _require_admin(staff)
        async with self._uow() as uow:
            queue = Queue(
                venue_id=staff.venue_id,
                name=name,
                default_service_sec=default_service_sec,
                no_show_grace_sec=no_show_grace_sec,
                max_requeues=max_requeues,
            )
            uow.queues.add(queue)
            await uow.queues.flush()
            for i in range(counters):
                uow.queues.add(Counter(queue_id=queue.id, label=f"Counter {i + 1}"))
            await uow.commit()
            return queue_dict(queue, await uow.queues.counters(queue.id))

    async def list(self, staff: StaffUser) -> list[dict]:
        async with self._uow() as uow:
            return [
                queue_dict(q, await uow.queues.counters(q.id))
                for q in await uow.queues.list_for_venue(staff.venue_id)
            ]

    async def get(self, staff: StaffUser, queue_id: int) -> dict:
        async with self._uow() as uow:
            q = await self._queue(uow, staff, queue_id)
            return queue_dict(q, await uow.queues.counters(q.id))

    async def update(self, staff: StaffUser, queue_id: int, changes: dict) -> dict:
        """Pause / close / reopen and tune settings. Broadcast like any other event."""
        _require_admin(staff)
        async with self._uow() as uow:
            await self._queue(uow, staff, queue_id)
            queue = await uow.queues.lock(queue_id)
            before = queue.status
            for field, value in changes.items():
                setattr(queue, field, value)
            await uow.emit(
                queue_id,
                QueueEventType.QUEUE_UPDATED,
                actor=actor(staff),
                payload={"changes": changes, "status_before": before},
            )
            await uow.commit()
            await uow.session.refresh(queue)
            return queue_dict(queue, await uow.queues.counters(queue_id))

    async def set_counter_active(self, staff: StaffUser, counter_id: int, active: bool) -> dict:
        _require_admin(staff)
        async with self._uow() as uow:
            counter = await uow.queues.get_counter(counter_id)
            if counter is None:
                raise NotFound("Counter not found.")
            await self._queue(uow, staff, counter.queue_id)
            counter.active = active
            await uow.emit(
                counter.queue_id,
                QueueEventType.QUEUE_UPDATED,
                actor=actor(staff),
                payload={"counter_id": counter_id, "active": active},
            )
            await uow.commit()
            return {"id": counter.id, "label": counter.label, "active": counter.active}

    async def join_qr(self, staff: StaffUser, queue_id: int) -> dict:
        async with self._uow() as uow:
            await self._queue(uow, staff, queue_id)
        token = self._join_tokens.issue(queue_id, self._today())
        url = f"{self._base}/join/{queue_id}?t={token}"
        return {"join_url": url, "join_token": token, "png_base64": qr_png_base64(url)}

    async def counter_nonce(self, staff: StaffUser, counter_id: int) -> dict:
        async with self._uow() as uow:
            counter = await uow.queues.get_counter(counter_id)
            if counter is None:
                raise NotFound("Counter not found.")
            await self._queue(uow, staff, counter.queue_id)
        now = self._clock()
        nonce = self._nonces.issue(counter_id, now)
        url = f"{self._base}/checkin?counter={counter_id}&nonce={nonce}"
        return {
            "counter_id": counter_id,
            "nonce": nonce,
            "expires_in": round(self._nonces.expires_in(now), 1),
            "checkin_url": url,
            "png_base64": qr_png_base64(url),
        }

    async def public(self, queue_id: int) -> dict:
        async with self._uow() as uow:
            board = await self._snapshots.board(uow, queue_id)
        if board is None:
            raise NotFound("Queue not found.")
        return board

    async def stats(self, staff: StaffUser, queue_id: int) -> dict:
        """Served count, average wait, and ETA accuracy measured per called ticket (ADR-0007)."""
        async with self._uow() as uow:
            queue = await self._queue(uow, staff, queue_id)
            samples = await uow.tickets.wait_samples(queue_id)
            counts = await uow.tickets.status_counts(queue_id)
        waits = [float(s["waited_sec"]) for s in samples]
        errors = [
            abs(float(s["eta_at_join_sec"]) - float(s["waited_sec"])) / float(s["waited_sec"])
            for s in samples
            if s["eta_at_join_sec"] is not None and float(s["waited_sec"]) >= self._min_wait
        ]
        return {
            "queue_id": queue_id,
            "status_counts": counts,
            "served": counts.get("served", 0),
            "called_total": len(samples),
            "avg_wait_sec": round(statistics.mean(waits), 1) if waits else None,
            "est_service_sec": queue.est_service_sec,
            "default_service_sec": queue.default_service_sec,
            "eta_error_samples": len(errors),
            "eta_median_ape": round(statistics.median(errors), 4) if errors else None,
            "eta_mape": round(statistics.mean(errors), 4) if errors else None,
            "eta_error_min_wait_sec": self._min_wait,
        }
