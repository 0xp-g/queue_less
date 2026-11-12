# ADR-0006: Publish only after commit (Unit of Work)

**Status:** Accepted

## Context
If we publish "ticket 36 called" and the transaction then rolls back, every screen shows a state that never existed.

## Decision
`UnitOfWork` wraps each use case: services call `uow.record(event)` during the transaction, and `uow.commit()` commits **then** publishes the buffered events. A rollback discards them. A publish failure after commit is logged and swallowed: the state is correct and clients resync through version gaps, snapshots and polling.

## Alternatives rejected
* **Publish inside the transaction:** this announces changes that might roll back.
* **Transactional outbox + dispatcher:** guaranteed delivery, but for best-effort UI hints the snapshot mechanism already covers loss. It's the documented upgrade path if delivery must be guaranteed (e.g. for SMS notifications).

## Consequences
* There's a small window between commit and publish where a crash loses the event, and that's acceptable for UI freshness.
* The pattern is consistent with OpsFlow, so the projects tell one story.
