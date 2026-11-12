# ADR-0010: Layered modular monolith; services composed through DI

**Status:** Accepted

## Context
The domain is small but has tricky invariants (concurrency, state transitions, publish-after-commit). The code must be testable without infrastructure and explainable in an interview file by file.

## Decision
Layers are `api → services → domain / repositories → db`. Dependencies point inward:
* `domain/` is pure Python (state machine, estimator, tokens) with zero framework imports.
* `repositories/` own all SQL.
* `services/` hold use cases, are **composed** of repositories, estimator, publisher and state machine (constructor injection), and own the transaction boundary through `UnitOfWork`.
* `api/` is thin: validate, authorize, call a service, map errors.
* `create_app()` is the composition root that wires concrete classes (Redis vs in-memory publisher).

## Alternatives rejected
* **Fat routers with SQL inline:** quick to write, but concurrency logic gets duplicated and is hard to test.
* **Microservices (queue service, notification service):** the domain is too small. Splitting would turn local transactions into distributed ones.
* **Full hexagonal/DDD with aggregates:** more abstraction than six tables justify.

## Consequences
* There are more files than a minimal FastAPI app, but each has one reason to change.
* Services are reused by HTTP handlers, the sweeper and tests.
