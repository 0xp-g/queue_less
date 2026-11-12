from dataclasses import asdict, dataclass
from enum import StrEnum


class QueueEventType(StrEnum):
    JOINED = "joined"
    CALLED = "called"
    CHECKED_IN = "checked_in"
    SERVED = "served"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    REQUEUED = "requeued"
    QUEUE_UPDATED = "queue_updated"


@dataclass(frozen=True)
class DomainEvent:
    """What gets published after commit. Deliberately tiny: receivers re-read the truth."""

    queue_id: int
    type: str
    version: int
    ticket_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)
