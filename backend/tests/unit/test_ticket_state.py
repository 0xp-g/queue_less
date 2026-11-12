import pytest

from app.core.errors import InvalidTransition
from app.domain.ticket_state import TicketAction, TicketStateMachine, TicketStatus

sm = TicketStateMachine()
LEGAL = TicketStateMachine.transitions()


@pytest.mark.parametrize(("src", "action", "dst"), [(s, a, d) for (s, a), d in LEGAL.items()])
def test_legal_transitions(src, action, dst):
    assert sm.next_status(src, action) == dst


ILLEGAL = [(s, a) for s in TicketStatus for a in TicketAction if (s, a) not in LEGAL]


@pytest.mark.parametrize(("src", "action"), ILLEGAL)
def test_every_other_transition_is_rejected(src, action):
    with pytest.raises(InvalidTransition):
        sm.next_status(src, action)


def test_terminal_states_allow_nothing():
    assert sm.allowed_actions("served") == []
    assert sm.allowed_actions("cancelled") == []


def test_staff_can_complete_without_check_in():
    assert sm.can("called", TicketAction.COMPLETE)
