"""Event publishing - Observer/pub-sub with interchangeable transports (Adapter pattern).

Services never know who listens. In production the Redis adapter fans events out to every API
instance; tests and single-process runs use the in-memory adapter (same interface, LSP).
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from app.domain.events import DomainEvent

log = logging.getLogger(__name__)

Listener = Callable[[DomainEvent], Awaitable[None]]
CHANNEL_PREFIX = "queue:"


def channel_for(queue_id: int) -> str:
    return f"{CHANNEL_PREFIX}{queue_id}"


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...


class InMemoryEventPublisher(EventPublisher):
    """Delivers directly to local listeners (single process / tests)."""

    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self.published: list[DomainEvent] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)
        for listener in self._listeners:
            await listener(event)


class RedisEventPublisher(EventPublisher):
    """PUBLISH queue:{id} {...}. At-most-once: receivers heal gaps with versions/snapshots."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def publish(self, event: DomainEvent) -> None:
        await self._redis.publish(channel_for(event.queue_id), json.dumps(event.to_dict()))
