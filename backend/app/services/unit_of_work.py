"""Unit of Work (ADR-0006): one transaction per use case; events are published AFTER commit.

    async with uow_factory() as uow:
        ... await uow.tickets.call_next(...)
        await uow.emit(queue_id, QueueEventType.CALLED, actor="staff:3", ticket_id=...)
        await uow.commit()          # commit, THEN publish buffered events

If the block raises, the transaction rolls back and buffered events are discarded, so we never
announce a change that did not happen.
"""

import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.events import DomainEvent, QueueEventType
from app.events.publisher import EventPublisher
from app.repositories.event_repo import EventRepository
from app.repositories.queue_repo import QueueRepository
from app.repositories.ticket_repo import TicketRepository

log = logging.getLogger(__name__)


class UnitOfWork:
    session: AsyncSession
    queues: QueueRepository
    tickets: TicketRepository
    events: EventRepository

    def __init__(self, session_factory: async_sessionmaker, publisher: EventPublisher):
        self._session_factory = session_factory
        self._publisher = publisher
        self._pending: list[DomainEvent] = []

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        self.queues = QueueRepository(self.session)
        self.tickets = TicketRepository(self.session)
        self.events = EventRepository(self.session)
        self._pending = []
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            await self.session.close()

    async def emit(
        self,
        queue_id: int,
        type_: QueueEventType,
        *,
        actor: str,
        ticket_id: int | None = None,
        payload: dict | None = None,
        version: int | None = None,
    ) -> int:
        """Record a domain event: bump the queue version (unless the caller already did, as
        the join CTE does), append the audit row, and buffer the publish until commit."""
        if version is None:
            version = await self.queues.bump_version(queue_id)
        self.events.append(queue_id, type_.value, version, actor, ticket_id, payload)
        self._pending.append(DomainEvent(queue_id, type_.value, version, ticket_id))
        return version

    async def commit(self) -> None:
        await self.session.commit()
        events, self._pending = self._pending, []
        for event in events:
            try:
                await self._publisher.publish(event)
            except Exception:  # state is committed; clients heal via version gaps / polling
                log.warning("publish failed after commit: %s", event, exc_info=True)

    async def rollback(self) -> None:
        self._pending = []
        await self.session.rollback()


UowFactory = Callable[[], UnitOfWork]
