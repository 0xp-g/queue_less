"""Domain error hierarchy (ADR-0011).

Services raise these; one FastAPI exception handler maps them to HTTP. Services never import
FastAPI, so the same use cases run from HTTP handlers, the sweeper and tests.
"""


class DomainError(Exception):
    code = "DOMAIN_ERROR"
    http_status = 400

    def __init__(self, message: str | None = None, *, code: str | None = None):
        self.message = message or self.__class__.__doc__ or self.code
        if code:
            self.code = code
        super().__init__(self.message)


class NotFound(DomainError):
    """Resource not found."""

    code = "NOT_FOUND"
    http_status = 404


class AuthError(DomainError):
    """Invalid credentials or token."""

    code = "UNAUTHENTICATED"
    http_status = 401


class Forbidden(DomainError):
    """Not allowed for this role."""

    code = "FORBIDDEN"
    http_status = 403


class InvalidToken(DomainError):
    """The QR token, ticket token or counter nonce is invalid or expired."""

    code = "INVALID_TOKEN"
    http_status = 403


class Conflict(DomainError):
    code = "CONFLICT"
    http_status = 409


class QueueNotOpen(Conflict):
    """The queue is not accepting this action in its current status."""

    code = "QUEUE_NOT_OPEN"


class InvalidTransition(Conflict):
    """This action is not allowed from the ticket's current status."""

    code = "INVALID_TRANSITION"


class TransitionConflict(Conflict):
    """The ticket was changed by someone else at the same time; refresh and retry."""

    code = "TRANSITION_CONFLICT"


class ActiveTicketExists(Conflict):
    """This device already holds an active ticket in this queue."""

    code = "ACTIVE_TICKET_EXISTS"


class RequeueLimit(Conflict):
    """This ticket has already used its requeue."""

    code = "REQUEUE_LIMIT"


class QueueEmpty(NotFound):
    """Nobody is waiting in this queue."""

    code = "QUEUE_EMPTY"


class RateLimited(DomainError):
    """Too many requests; try again shortly."""

    code = "RATE_LIMITED"
    http_status = 429
