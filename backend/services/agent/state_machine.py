from core.errors import ApiError
from models.enums import AgentRunStatus


ALLOWED_TRANSITIONS: dict[AgentRunStatus, set[AgentRunStatus]] = {
    AgentRunStatus.COLLECTING: {
        AgentRunStatus.DIAGNOSING,
        AgentRunStatus.DRAFTING,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.DIAGNOSING: {
        AgentRunStatus.DIAGNOSING,
        AgentRunStatus.DRAFTING,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.DRAFTING: {
        AgentRunStatus.DRAFTING,
        AgentRunStatus.AWAITING_CONFIRMATION,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.AWAITING_CONFIRMATION: {
        AgentRunStatus.COLLECTING,
        AgentRunStatus.DRAFTING,
        AgentRunStatus.COMPLETED,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.ASSESSING: {
        AgentRunStatus.ASSESSING,
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.FAILED: {
        AgentRunStatus.COLLECTING,
        AgentRunStatus.DIAGNOSING,
        AgentRunStatus.DRAFTING,
        AgentRunStatus.ASSESSING,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.COMPLETED: set(),
    AgentRunStatus.CANCELLED: set(),
}


def transition(current: AgentRunStatus | str, target: AgentRunStatus | str) -> AgentRunStatus:
    current_status = AgentRunStatus(current)
    target_status = AgentRunStatus(target)
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message=f"流程不能从 {current_status.value} 转换到 {target_status.value}",
            retryable=False,
        )
    return target_status
