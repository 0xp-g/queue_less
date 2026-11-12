"""Join rate limiting (ADR-0004). Strategy + Null Object: services just call allow()."""

import logging
import time
from abc import ABC, abstractmethod

from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)


class RateLimiter(ABC):
    @abstractmethod
    async def allow(self, key: str) -> bool: ...


class NoopRateLimiter(RateLimiter):
    async def allow(self, key: str) -> bool:
        return True


class RedisFixedWindowRateLimiter(RateLimiter):
    """INCR a per-key counter for the current minute. Fails OPEN if Redis is down (logged):
    a Redis outage should degrade abuse protection, not stop visitors joining."""

    def __init__(self, redis: Redis, limit_per_min: int):
        self._redis = redis
        self._limit = limit_per_min

    async def allow(self, key: str) -> bool:
        bucket = f"rate:{key}:{int(time.time() // 60)}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                count, _ = await pipe.incr(bucket).expire(bucket, 120).execute()
        except RedisError:
            log.warning("rate limiter unavailable; allowing request", exc_info=True)
            return True
        return count <= self._limit
