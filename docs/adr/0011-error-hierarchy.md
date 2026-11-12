# ADR-0011: Domain error hierarchy mapped to HTTP in one place

**Status:** Accepted

## Context
Services shouldn't know about HTTP, yet clients need precise status codes and a stable error shape.

## Decision
`core/errors.py` defines `DomainError(code, message, http_status)` with subclasses: `NotFound` (404), `InvalidToken` (403), `QueueNotOpen` (409), `InvalidTransition` (409), `TransitionConflict` (409), `ActiveTicketExists` (409), `RequeueLimit` (409), `RateLimited` (429), `AuthError` (401), `Forbidden` (403). One FastAPI exception handler renders `{"error": {"code", "message"}}`. Pydantic validation errors are rendered as 400 with the same shape.

## Alternatives rejected
* **`HTTPException` raised from services:** couples the domain to the web framework.
* **Return codes / Result objects:** not idiomatic Python, and easy to ignore.

## Consequences
* One mapping table to reason about; API tests assert both status and `error.code`.
