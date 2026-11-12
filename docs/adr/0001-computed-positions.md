# ADR-0001: Positions are computed, never stored

**Status:** Accepted

## Context
Every visitor needs "you are #N". The obvious design is a `position` column. But every call-next, cancellation or no-show would then rewrite **every waiting row behind it**: O(n) writes per event, wide row locks, and contention exactly when the queue is busiest.

## Decision
Each ticket gets an immutable, per-queue, increasing `seq` assigned at join. Position is derived:
`position = (count of waiting tickets in the same queue with smaller seq) + 1`.
A partial index `tickets(queue_id, seq) WHERE status = 'waiting'` keeps that count cheap. For fan-out, one `row_number() OVER (ORDER BY seq)` query per event per API instance computes everyone's position at once.

## Alternatives rejected
* **Stored position column:** O(n) writes per event and lock contention.
* **Redis sorted set as the queue:** fast `ZRANK`, but not durable or transactional with ticket state, so there are two sources of truth.

## Consequences
* Every state change touches **one** ticket row.
* `seq` can have gaps (an idempotent retry consumes a number before the conflict is detected). That's harmless because `seq` orders tickets; it isn't shown as the position.
* Reading a position costs an indexed count. That's fine at our scale; at stadium scale, push deltas and let clients compute their position.
