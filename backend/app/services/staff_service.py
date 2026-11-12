"""Staff use cases: call next, complete, no-show, requeue, cancel, check-in (design B6).

Every query is scoped to the authenticated staff member's venue (ADR-0009). A ticket or queue in
another venue raises NotFound, not Forbidden, so its existence is not leaked.
"""

from sqlalchemy import func, select

from app.core.errors import NotFound, QueueEmpty, QueueNotOpen, RequeueLimit, TransitionConflict
from app.db.models import Queue, StaffUser, Ticket
from app.domain.estimator import EtaEstimator
from app.domain.events import QueueEventType
from app.domain.ticket_state import TicketAction, TicketStateMachine, TicketStatus
from app.services.snapshot_service import SnapshotService
from app.services.unit_of_work import UnitOfWork, UowFactory


def actor(staff: StaffUser) -> str:
    return f"staff:{staff.id}"


def ticket_dict(t: Ticket) -> dict:
    return {
        "id": t.id,
        "ticket_id": t.id,
        "queue_id": t.queue_id,
        "seq": t.seq,
        "status": t.status,
        "counter_id": t.counter_id,
        "requeue_count": t.requeue_count,
        "joined_at": t.joined_at,
        "called_at": t.called_at,
        "checked_in_at": t.checked_in_at,
        "served_at": t.served_at,
    }


class StaffService:
    def __init__(
        self,
        uow: UowFactory,
        state_machine: TicketStateMachine,
        estimator: EtaEstimator,
        snapshots: SnapshotService,
    ):
        self._uow = uow
        self._sm = state_machine
        self._estimator = estimator
        self._snapshots = snapshots

    # --- helpers ---------------------------------------------------------------------------
    @staticmethod
    async def _queue(uow: UnitOfWork, staff: StaffUser, queue_id: int) -> Queue:
        queue = await uow.queues.get_for_venue(queue_id, staff.venue_id)
        if queue is None:
            raise NotFound("Queue not found.")
        return queue

    @staticmethod
    async def _ticket(uow: UnitOfWork, staff: StaffUser, ticket_id: int) -> tuple[Ticket, Queue]:
        ticket = await uow.tickets.get(ticket_id)
        queue = await uow.queues.get(ticket.queue_id) if ticket else None
        if ticket is None or queue is None or queue.venue_id != staff.venue_id:
            raise NotFound("Ticket not found.")
        return ticket, queue

    async def _transition(
        self,
        uow: UnitOfWork,
        ticket: Ticket,
        action: TicketAction,
        event: QueueEventType,
        staff: StaffUser,
        **fields,
    ) -> None:
        new = self._sm.next_status(ticket.status, action)  # InvalidTransition -> 409
        if not await uow.tickets.transition(ticket.id, ticket.status, new, **fields):
            raise TransitionConflict()  # somebody else changed it first -> 409
        await uow.emit(ticket.queue_id, event, actor=actor(staff), ticket_id=ticket.id)

    # --- use cases -------------------------------------------------------------------------
    async def call_next(self, staff: StaffUser, queue_id: int, counter_id: int | None) -> dict:
        async with self._uow() as uow:
            queue = await self._queue(uow, staff, queue_id)
            if queue.status == "closed":  # paused queues keep serving; closed ones do not
                raise QueueNotOpen("This queue is closed.")
            if counter_id is not None:
                counter = await uow.queues.get_counter(counter_id)
                if counter is None or counter.queue_id != queue_id:
                    raise NotFound("Counter not found in this queue.")
            called = await uow.tickets.call_next(queue_id, counter_id)  # SKIP LOCKED
            if called is None:
                raise QueueEmpty()
            version = await uow.emit(
                queue_id,
                QueueEventType.CALLED,
                actor=actor(staff),
                ticket_id=called.ticket_id,
                payload={"seq": called.seq, "counter_id": counter_id},
            )
            await uow.commit()
        return {
            "id": called.ticket_id,
            "ticket_id": called.ticket_id,
            "seq": called.seq,
            "counter_id": counter_id,
            "version": version,
        }

    async def complete(self, staff: StaffUser, ticket_id: int) -> dict:
        async with self._uow() as uow:
            ticket, _ = await self._ticket(uow, staff, ticket_id)
            # now() is the transaction start time: one consistent clock for served_at and the
            # observed service duration.
            db_now = await uow.session.scalar(select(func.now()))
            await self._transition(
                uow,
                ticket,
                TicketAction.COMPLETE,
                QueueEventType.SERVED,
                staff,
                served_at=db_now,
                closed_at=db_now,
            )
            # Update the rolling estimate under the queue row lock (ticket -> queue lock order).
            queue = await uow.queues.lock(ticket.queue_id)
            observed = (db_now - ticket.called_at).total_seconds()
            current = queue.est_service_sec or queue.default_service_sec
            queue.est_service_sec = self._estimator.update(current, observed)
            await uow.commit()
            return ticket_dict(await uow.tickets.get(ticket.id))

    async def mark_no_show(self, staff: StaffUser, ticket_id: int) -> dict:
        async with self._uow() as uow:
            ticket, _ = await self._ticket(uow, staff, ticket_id)
            await self._transition(
                uow,
                ticket,
                TicketAction.NO_SHOW,
                QueueEventType.NO_SHOW,
                staff,
                closed_at=func.now(),
            )
            await uow.commit()
            return ticket_dict(await uow.tickets.get(ticket.id))

    async def cancel(self, staff: StaffUser, ticket_id: int) -> dict:
        async with self._uow() as uow:
            ticket, _ = await self._ticket(uow, staff, ticket_id)
            await self._transition(
                uow,
                ticket,
                TicketAction.CANCEL,
                QueueEventType.CANCELLED,
                staff,
                closed_at=func.now(),
            )
            await uow.commit()
            return ticket_dict(await uow.tickets.get(ticket.id))

    async def check_in(self, staff: StaffUser, ticket_id: int) -> dict:
        """Staff override for visitors who cannot scan (no camera, dead phone)."""
        async with self._uow() as uow:
            ticket, _ = await self._ticket(uow, staff, ticket_id)
            await self._transition(
                uow,
                ticket,
                TicketAction.CHECK_IN,
                QueueEventType.CHECKED_IN,
                staff,
                checked_in_at=func.now(),
            )
            await uow.commit()
            return ticket_dict(await uow.tickets.get(ticket.id))

    async def requeue(self, staff: StaffUser, ticket_id: int) -> dict:
        """One second chance for a no-show: back of the line with a fresh seq."""
        async with self._uow() as uow:
            ticket, queue = await self._ticket(uow, staff, ticket_id)
            self._sm.next_status(ticket.status, TicketAction.REQUEUE)
            if ticket.requeue_count >= queue.max_requeues:
                raise RequeueLimit()
            if queue.status == "closed":
                raise QueueNotOpen("This queue is closed.")
            if not await uow.tickets.transition(
                ticket.id, TicketStatus.NO_SHOW, TicketStatus.WAITING
            ):
                raise TransitionConflict()
            locked = await uow.queues.lock(queue.id)  # ticket -> queue lock order
            locked.next_seq += 1
            new_seq = locked.next_seq
            await uow.tickets.move_to_back(ticket.id, new_seq)
            await uow.emit(
                queue.id,
                QueueEventType.REQUEUED,
                actor=actor(staff),
                ticket_id=ticket.id,
                payload={"new_seq": new_seq},
            )
            await uow.commit()
            return ticket_dict(await uow.tickets.get(ticket.id))

    async def list_tickets(
        self, staff: StaffUser, queue_id: int, statuses: tuple[str, ...]
    ) -> list[dict]:
        async with self._uow() as uow:
            await self._queue(uow, staff, queue_id)
            return [ticket_dict(t) for t in await uow.tickets.list_for_queue(queue_id, statuses)]
