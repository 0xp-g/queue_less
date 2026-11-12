"""Bridges Redis pub/sub into this instance's ConnectionManager (ADR-0005).

One subscriber connection per API instance (pattern queue:*). Pub/sub is at-most-once, so after
every (re)connect we resync all local sockets: anything missed while disconnected is healed.
"""

import asyncio
import json
import logging

from redis.asyncio import Redis

from app.domain.events import DomainEvent
from app.events.publisher import CHANNEL_PREFIX
from app.realtime.hub import ConnectionManager

log = logging.getLogger(__name__)


class RedisEventListener:
    def __init__(self, redis_url: str, hub: ConnectionManager, max_backoff: float = 10.0):
        self._redis_url = redis_url
        self._hub = hub
        self._max_backoff = max_backoff
        self.connected = asyncio.Event()

    async def run(self) -> None:
        backoff = 0.5
        while True:
            redis = Redis.from_url(self._redis_url, decode_responses=True)
            try:
                async with redis.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
                    self.connected.set()
                    backoff = 0.5
                    await self._hub.resync_all()
                    async for message in pubsub.listen():
                        if message["type"] == "pmessage":
                            await self._dispatch(message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                self.connected.clear()
                log.warning("redis listener disconnected; retrying in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(self._max_backoff, backoff * 2)
            finally:
                await redis.aclose()

    async def _dispatch(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            event = DomainEvent(
                queue_id=int(data["queue_id"]),
                type=str(data["type"]),
                version=int(data["version"]),
                ticket_id=data.get("ticket_id"),
            )
        except (ValueError, KeyError, TypeError):
            log.warning("ignoring malformed event %r", raw)
            return
        await self._hub.on_event(event)
