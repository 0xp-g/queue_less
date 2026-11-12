# ADR-0003: Table-driven state machine plus compare-and-set transitions

**Status:** Accepted

## Context
A ticket moves through `waiting → called → serving → served`, with side exits to `cancelled` and `no_show` and one `requeue`. Several actors can race on the same ticket: the visitor cancels while staff marks no-show, the sweeper fires while staff completes.

## Decision
1. **State pattern, table-driven:** `TicketStateMachine` holds `{(current_status, action): next_status}`. Asking for an illegal transition raises `InvalidTransition` (HTTP 409). Adding a state or action is a data change, not a new if/else branch (Open/Closed principle).
2. **Compare-and-set in SQL:** the repository executes `UPDATE tickets SET status = :to ... WHERE id = :id AND status = :from`. Zero affected rows means another actor changed the ticket first, so it raises `TransitionConflict` (409).

## Alternatives rejected
* **Class-per-state (GoF State with subclasses):** too much ceremony for six states with no per-state behaviour beyond the transition table.
* **`SELECT ... FOR UPDATE` then check then update:** also correct, but holds a lock across a round trip. CAS is one statement.
* **Checking in Python only:** races between read and write.

## Consequences
* Every race on a ticket has exactly one winner, and the loser gets a clear 409.
* The transition table doubles as documentation and drives the unit tests, which enumerate all (state, action) pairs.
