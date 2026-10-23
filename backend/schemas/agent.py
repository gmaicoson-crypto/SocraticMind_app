from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.enums import AgentRunStatus, AgentRunType, Familiarity, OutcomeType


class OnboardingRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=300)
    domain: str = Field(min_length=1, max_length=100)
    outcome_type: OutcomeType
    familiarity: Familiarity
    daily_minutes: int = Field(default=30, ge=5, le=240)
    target_date: date | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    use_diagnostic: bool = True
    session_id: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("topic", "goal", "domain", "timezone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AgentStep(BaseModel):
    step_id: str
    prompt: str
    input_type: str = "text"
    choices: list[str] = Field(default_factory=list)
    current: int
    total: int


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    type: AgentRunType
    status: AgentRunStatus
    version: int
    step: AgentStep | None = None
    preview: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class TopicPlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=300)
    domain: str = Field(min_length=1, max_length=100)
    outcome_type: OutcomeType
    familiarity: Familiarity
    daily_minutes: int = Field(default=30, ge=5, le=240)
    target_date: date | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    use_diagnostic: bool = False
    session_id: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("goal", "domain", "timezone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AgentAnswerRequest(BaseModel):
    step_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=5000)


class ConfirmRunRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)


class RunUpdateRequest(BaseModel):
    goal: str | None = Field(default=None, min_length=1, max_length=300)
    daily_minutes: int | None = Field(default=None, ge=5, le=240)
    target_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("goal", "timezone")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def require_a_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


__all__ = [
    "AgentRunResponse",
    "AgentRunStatus",
    "AgentRunType",
    "AgentStep",
    "AgentAnswerRequest",
    "ConfirmRunRequest",
    "Familiarity",
    "OnboardingRequest",
    "OutcomeType",
    "RunUpdateRequest",
    "TopicPlanRequest",
]
