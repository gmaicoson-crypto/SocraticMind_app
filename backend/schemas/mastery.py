from pydantic import BaseModel, Field

from models.enums import AssessmentStatus, MasterySource


class MasteryRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)


class StartAssessmentRequest(BaseModel):
    node_id: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)


class AssessmentAnswerRequest(BaseModel):
    step_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=5000)


__all__ = [
    "AssessmentAnswerRequest",
    "AssessmentStatus",
    "MasteryRequest",
    "MasterySource",
    "StartAssessmentRequest",
]
