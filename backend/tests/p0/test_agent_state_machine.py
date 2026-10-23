import pytest

from core.errors import ApiError
from models.enums import AgentRunStatus
from services.agent.state_machine import transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("collecting", "diagnosing"),
        ("collecting", "drafting"),
        ("diagnosing", "diagnosing"),
        ("diagnosing", "drafting"),
        ("drafting", "drafting"),
        ("drafting", "awaiting_confirmation"),
        ("awaiting_confirmation", "completed"),
        ("awaiting_confirmation", "collecting"),
        ("assessing", "completed"),
        ("failed", "drafting"),
        ("failed", "cancelled"),
    ],
)
def test_allowed_transitions(current, target):
    assert transition(current, target) == AgentRunStatus(target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("completed", "collecting"),
        ("cancelled", "drafting"),
        ("collecting", "completed"),
        ("awaiting_confirmation", "diagnosing"),
    ],
)
def test_invalid_transitions_return_state_conflict(current, target):
    with pytest.raises(ApiError) as error:
        transition(current, target)
    assert error.value.status_code == 409
    assert error.value.code == "AGENT_STATE_CONFLICT"
