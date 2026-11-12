# ADR-0005: Redis pub/sub fan-out with per-queue versions

**Status:** Accepted

## Context
Visitors' sockets are spread across several API instances. A staff action handled on instance A must reach sockets on instance B. Redis pub/sub is at-most-once: a subscriber that's briefly disconnected misses messages.

## Decision
* One channel per queue, `queue:{id}`. Every instance has one subscriber connection (pattern `queue:*`) and forwards messages to the `ConnectionManager`.
* Events are tiny: `{type, queue_id, version}`. `queues.version` is incremented **in the same transaction** as the change.
* On an event, each instance runs **one** ranked query for that queue and pushes each connected visitor their own `{now_serving, position, eta_seconds, version}`.
* Clients ignore events older than their version. If they see a gap they request a snapshot. Every (re)connect starts with a snapshot. The server pings every 25 s.

## Alternatives rejected
* **Redis Streams / Kafka:** durable and replayable, but we don't need replay because PostgreSQL is the truth and the snapshot heals gaps. Revisit if we need event history for clients.
* **PostgreSQL LISTEN/NOTIFY:** viable and one fewer service, but it ties fan-out to DB connections and we already need Redis for rate limiting. Mentioned as an alternative in interviews.
* **Sticky sessions with no cross-instance bus:** a staff action on another instance would never reach those sockets.

## Consequences
* Redis loss means *stale*, never *wrong*: clients fall back to polling.
* The cost per event is O(instances) queries, not O(visitors).
