"""Visitor use cases: join, status, cancel, check-in (design B6)."""

import time
from datetime import date

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    ActiveTicketExists,
    InvalidToken,
    NotFound,
    QueueNotOpen,
    RateLimited,
    TransitionConflict,
)
from app.core.rate_limit import RateLimiter
from app.db.models import Ticket
from app.domain.events import QueueEventType
from app.domain.ticket_state import TicketAction, TicketStateMachine
from app.domain.tokens import CounterNonceService, JoinTokenService, TicketTokens
from app.services.snapshot_service import SnapshotService
from app.services.unit_of_work import UowFactory


class TicketService:
    def __init__(
        self,
        uow: UowFactory,
        join_tokens: JoinTokenService,
        ticket_tokens: TicketTokens,
        counter_nonces: CounterNonceService,
        snapshots: SnapshotService,
        state_machine: TicketStateMachine,
        rate_limiter: RateLimiter,
        today=date.today,
        clock=time.time,
    ):
        self._uow = uow
        self._join_tokens = join_tokens
        self._ticket_tokens = ticket_tokens
        self._nonces = counter_nonces
        self._snapshots = snapshots
        self._sm = state_machine
        self._limiter = rate_limiter
        self._today = today
        self._clock = clock

    async def join(
        self,
        queue_id: int,
        join_token: str,
        client_request_id: str,
        device_id: str | None,
        client_ip: str,
    ) -> tuple[dict, bool]:
        """Returns (snapshot including the ticket token, created). A retried request with the
        same client_request_id returns the same ticket and token with created=False."""
        if not self._join_tokens.verify(queue_id, join_token, self._today()):
            raise InvalidToken("This QR code is invalid or has expired. Scan the current one.")
        if not await self._limiter.allow(f"join:{client_ip}"):
            raise RateLimited()

        token = self._ticket_tokens.issue(queue_id, client_request_id)
        token_hash = self._ticket_tokens.hash(token)

        async with self._uow() as uow:
            queue = await uow.queues.get(queue_id)
            if queue is None:
                raise NotFound("Queue not found.")

            replay = await uow.tickets.get_by_request(queue_id, client_request_id)
            if replay is not None:
                return await self._with_token(uow, replay, token), False
            if queue.status != "open":
                raise QueueNotOpen(f"This queue is {queue.status} and not accepting new joins.")
            if device_id and await uow.tickets.active_for_device(queue_id, device_id):
                raise ActiveTicketExists()

            try:
                joined = await uow.tickets.join_ticket(
                    queue_id, client_request_id, device_id, token_hash
                )
            except IntegrityError as exc:  # concurrent join from the same device
                raise ActiveTicketExists() from exc

            if joined is None:
                # Lost a race with a concurrent identical request, or the queue just closed.
                await uow.rollback()
                replay = await uow.tickets.get_by_request(queue_id, client_request_id)
                if replay is not None:
                    return await self._with_token(uow, replay, token), False
                raise QueueNotOpen("This queue stopped accepting joins.")

            ticket = await uow.tickets.get(joined.ticket_id)
            snapshot = await self._snapshots.for_ticket(uow, ticket)
            await uow.tickets.set_eta_at_join(ticket.id, snapshot["eta_seconds"])
            await uow.emit(
                queue_id,
                QueueEventType.JOINED,
                actor="visitor",
                ticket_id=ticket.id,
                version=joined.version,
                payload={"seq": joined.seq, "eta_sec": snapshot["eta_seconds"]},
            )
            await uow.commit()
            snapshot["version"] = joined.version
        return {**snapshot, "token": token}, True

    async def status(self, token: str) -> dict:
        async with self._uow() as uow:
            ticket = await self._by_token(uow, token)
            return await self._snapshots.for_ticket(uow, ticket)

    async def cancel(self, token: str) -> dict:
        async with self._uow() as uow:
            ticket = await self._by_token(uow, token)
            new = self._sm.next_status(ticket.status, TicketAction.CANCEL)
            if not await uow.tickets.transition(
                ticket.id, ticket.status, new, closed_at=func.now()
            ):
                raise TransitionConflict()
            await uow.emit(
                ticket.queue_id, QueueEventType.CANCELLED, actor="visitor", ticket_id=ticket.id
            )
            await uow.commit()
            ticket = await uow.tickets.get(ticket.id)
            return await self._snapshots.for_ticket(uow, ticket)

    async def check_in(self, ticket_id: int, token: str, counter_id: int, nonce: str) -> dict:
        """Visitor scans the counter QR. The rotating nonce proves physical presence."""
        if not self._nonces.verify(counter_id, nonce, self._clock()):
            raise InvalidToken("This counter code has expired. Scan the screen again.")
        async with self._uow() as uow:
            ticket = await self._by_token(uow, token)
            if ticket.id != ticket_id:
                raise InvalidToken("Ticket token does not match this ticket.")
            counter = await uow.queues.get_counter(counter_id)
            if counter is None or counter.queue_id != ticket.queue_id:
                raise InvalidToken("This counter belongs to a different queue.")
            if ticket.counter_id is not None and ticket.counter_id != counter_id:
                raise InvalidToken("You were called to a different counter.")
            new = self._sm.next_status(ticket.status, TicketAction.CHECK_IN)
            if not await uow.tickets.transition(
                ticket.id, ticket.status, new, checked_in_at=func.now(), counter_id=counter_id
            ):
                raise TransitionConflict()
            await uow.emit(
                ticket.queue_id, QueueEventType.CHECKED_IN, actor="visitor", ticket_id=ticket.id
            )
            await uow.commit()
            ticket = await uow.tickets.get(ticket.id)
            return await self._snapshots.for_ticket(uow, ticket)

    async def _by_token(self, uow, token: str) -> Ticket:
        ticket = await uow.tickets.get_by_token_hash(self._ticket_tokens.hash(token or ""))
        if ticket is None:
            raise NotFound("Ticket not found.")
        return ticket

    async def _with_token(self, uow, ticket: Ticket, token: str) -> dict:
        return {**await self._snapshots.for_ticket(uow, ticket), "token": token}
