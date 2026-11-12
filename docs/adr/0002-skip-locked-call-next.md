# ADR-0002: SKIP LOCKED for call-next; queue-row lock for join

**Status:** Accepted

## Context
Two hazards:
1. **Two counters press "call next" at the same instant.** A naive `SELECT first waiting` followed by `UPDATE` lets both transactions read the same row, so the same visitor is called twice (a lost update).
2. **Many visitors join at the same instant.** `max(seq)+1` races and produces duplicate numbers.

## Decision
* **Join:** a single CTE `UPDATE queues SET next_seq = next_seq + 1 ... RETURNING` then `INSERT ticket`. The UPDATE takes a row lock on *this queue's* row only, which serializes joins per queue while different queues proceed in parallel. `UNIQUE(queue_id, seq)` is the safety net.
* **Call-next:** `SELECT ... ORDER BY seq LIMIT 1 FOR UPDATE SKIP LOCKED` inside the UPDATE CTE. The second transaction *skips* the row the first has locked and takes the next one instead of blocking.

## Alternatives rejected
* **SERIALIZABLE isolation + retry:** correct but produces serialization failures under load that we'd have to retry.
* **`FOR UPDATE` without SKIP LOCKED:** correct, but the second counter waits for the first to commit. That's slower and still needs re-checking.
* **Application-level mutex / Redis lock:** doesn't work across instances without a distributed lock, and adds a failure mode.
* **PostgreSQL SEQUENCE per queue:** needs dynamic DDL per queue and can't be gated on `status = 'open'` in the same statement.

## Consequences
* Proven by `tests/integration/test_concurrency.py`: 45 concurrent joins (5 retries) give 40 tickets; 2 counters × 20 concurrent calls give 40 distinct tickets and 0 double calls.
* Joins for a single queue are serialized. Each holds the lock for about 1 ms, so roughly 1,000 joins/s per queue is the theoretical ceiling, far above need.
