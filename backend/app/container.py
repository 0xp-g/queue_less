"""Composition root (Factory + Dependency Injection, ADR-0010).

The only place that knows which concrete classes are used: Redis or in-memory publisher, EWMA or
fixed estimator, Redis or no-op rate limiter. Business code depends on the abstractions.
"""

from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.core.rate_limit import NoopRateLimiter, RateLimiter, RedisFixedWindowRateLimiter
from app.db.session import build_engine, build_session_factory
from app.domain.estimator import EtaEstimator, build_estimator
from app.domain.ticket_state import TicketStateMachine
from app.domain.tokens import CounterNonceService, JoinTokenService, TicketTokens, TokenSigner
from app.events.publisher import EventPublisher, InMemoryEventPublisher, RedisEventPublisher
from app.realtime.hub import ConnectionManager
from app.services.auth_service import AuthService
from app.services.queue_service import QueueService
from app.services.snapshot_service import SnapshotService
from app.services.staff_service import StaffService
from app.services.ticket_service import TicketService
from app.services.unit_of_work import UnitOfWork


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker
    redis: Redis | None
    publisher: EventPublisher
    estimator: EtaEstimator
    snapshots: SnapshotService
    auth: AuthService
    tickets: TicketService
    staff: StaffService
    queues: QueueService
    hub: ConnectionManager
    extras: dict = field(default_factory=dict)

    def uow(self) -> UnitOfWork:
        return UnitOfWork(self.session_factory, self.publisher)

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        await self.engine.dispose()


def build_container(settings: Settings) -> Container:
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)

    redis: Redis | None = None
    publisher: EventPublisher
    if settings.event_transport == "redis":
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        publisher = RedisEventPublisher(redis)
    else:
        publisher = InMemoryEventPublisher()

    limiter: RateLimiter = (
        RedisFixedWindowRateLimiter(redis, settings.join_rate_limit_per_min)
        if redis is not None and settings.join_rate_limit_per_min > 0
        else NoopRateLimiter()
    )

    signer = TokenSigner(settings.token_secret)
    join_tokens = JoinTokenService(signer)
    nonces = CounterNonceService(signer, settings.counter_nonce_window_sec)
    ticket_tokens = TicketTokens(signer)
    state_machine = TicketStateMachine()
    estimator = build_estimator(settings)
    snapshots = SnapshotService(estimator)

    def uow_factory() -> UnitOfWork:
        return UnitOfWork(session_factory, publisher)

    hub = ConnectionManager(uow_factory, snapshots)
    if isinstance(publisher, InMemoryEventPublisher):
        publisher.subscribe(hub.on_event)  # single process: deliver locally, no Redis hop

    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        redis=redis,
        publisher=publisher,
        estimator=estimator,
        snapshots=snapshots,
        auth=AuthService(session_factory, settings),
        tickets=TicketService(
            uow_factory, join_tokens, ticket_tokens, nonces, snapshots, state_machine, limiter
        ),
        staff=StaffService(uow_factory, state_machine, estimator, snapshots),
        queues=QueueService(
            uow_factory,
            join_tokens,
            nonces,
            snapshots,
            settings.public_base_url,
            settings.eta_error_min_wait_sec,
        ),
        hub=hub,
    )
