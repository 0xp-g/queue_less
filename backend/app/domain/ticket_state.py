"""Ticket lifecycle as a table-driven state machine (ADR-0003).

Legal transitions are data, not if/else chains: adding a state or action is a table edit
(Open/Closed principle). The repository additionally enforces each transition with a
compare-and-set UPDATE, so concurrent actors cannot both win.
"""

from enum import StrEnum

from app.core.errors import InvalidTransition


class TicketStatus(StrEnum):
    WAITING = "waiting"
    CALLED = "called"
    SERVING = "serving"
    SERVED = "served"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class TicketAction(StrEnum):
    CALL = "call"
    CANCEL = "cancel"
    CHECK_IN = "check_in"
    COMPLETE = "complete"
    NO_SHOW = "no_show"
    REQUEUE = "requeue"


ACTIVE_STATUSES = frozenset({TicketStatus.WAITING, TicketStatus.CALLED, TicketStatus.SERVING})
TERMINAL_STATUSES = frozenset({TicketStatus.SERVED, TicketStatus.CANCELLED})


class TicketStateMachine:
    S, A = TicketStatus, TicketAction
    _TRANSITIONS: dict[tuple[TicketStatus, TicketAction], TicketStatus] = {
        (S.WAITING, A.CALL): S.CALLED,
        (S.WAITING, A.CANCEL): S.CANCELLED,
        (S.CALLED, A.CHECK_IN): S.SERVING,
        (S.CALLED, A.COMPLETE): S.SERVED,  # staff may complete without a QR check-in
        (S.CALLED, A.CANCEL): S.CANCELLED,
        (S.CALLED, A.NO_SHOW): S.NO_SHOW,
        (S.SERVING, A.COMPLETE): S.SERVED,
        (S.NO_SHOW, A.REQUEUE): S.WAITING,  # limited by queues.max_requeues
    }

    def next_status(self, current: str, action: TicketAction) -> TicketStatus:
        try:
            return self._TRANSITIONS[(TicketStatus(current), action)]
        except KeyError:
            raise InvalidTransition(
                f"Cannot {action.value.replace('_', ' ')} a ticket that is {current}."
            ) from None

    def can(self, current: str, action: TicketAction) -> bool:
        return (TicketStatus(current), action) in self._TRANSITIONS

    def allowed_actions(self, current: str) -> list[TicketAction]:
        status = TicketStatus(current)
        return [action for (src, action) in self._TRANSITIONS if src == status]

    @classmethod
    def transitions(cls) -> dict[tuple[TicketStatus, TicketAction], TicketStatus]:
        return dict(cls._TRANSITIONS)
