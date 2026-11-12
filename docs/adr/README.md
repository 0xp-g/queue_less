# Architecture Decision Records

Each ADR records one decision: the context, what we chose, the alternatives we rejected, and the consequences we accept. Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

| # | Decision | Area |
|---|---|---|
| [0001](0001-computed-positions.md) | Positions are computed from `seq`, never stored | Data model |
| [0002](0002-skip-locked-call-next.md) | `FOR UPDATE SKIP LOCKED` for call-next; queue-row lock for join | Concurrency |
| [0003](0003-state-machine-cas-transitions.md) | Table-driven ticket state machine plus compare-and-set updates | Domain / concurrency |
| [0004](0004-qr-token-design.md) | HMAC join tokens, hashed ticket tokens, rotating counter nonces | Security |
| [0005](0005-redis-pubsub-versioned-events.md) | Redis pub/sub fan-out with per-queue versions | Realtime |
| [0006](0006-publish-after-commit.md) | Publish events only after commit (Unit of Work) | Consistency |
| [0007](0007-ewma-eta-estimator.md) | EWMA service-time estimator behind a Strategy interface | Algorithm |
| [0008](0008-no-show-sweeper-in-process.md) | In-process idempotent no-show sweeper, no Celery | Operations |
| [0009](0009-staff-jwt-venue-scope.md) | Staff JWT, reload the user, scope by venue from the principal | Security / tenancy |
| [0010](0010-layered-architecture.md) | Layered modular monolith; services composed by DI | Code structure |
| [0011](0011-error-hierarchy.md) | Domain error hierarchy mapped to HTTP in one place | API design |
