# ADR-0008: In-process idempotent no-show sweeper, no Celery

**Status:** Accepted

## Context
A called ticket that isn't checked in within `no_show_grace_sec` (default 120 s) must become `no_show`. Something must run periodically.

## Decision
An `asyncio` task started in the FastAPI lifespan runs every 10 s:
`UPDATE tickets SET status='no_show' WHERE status='called' AND called_at < now() - grace RETURNING ...`, then publishes an event per affected queue. The statement is **idempotent**: if several API instances run it, the second one matches zero rows.

## Alternatives rejected
* **Celery beat + worker:** adds a broker role, a worker process and a scheduler process for one SQL statement. Celery is justified in RepoLens and Deploy-Lite, where tasks take minutes; here it isn't.
* **Per-ticket timers (`asyncio.sleep` per call):** lost on restart, and duplicated across instances.

## Consequences
* With N instances the sweep runs N times per interval, which is harmless and cheap. If the sweeper ever does non-idempotent work, add leader election with `pg_try_advisory_lock`.
* A no-show is detected within at most grace + 10 s.
