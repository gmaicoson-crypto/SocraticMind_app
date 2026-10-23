from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from models.enums import OutcomeType, PlanItemStatus, PlanStatus


class PlanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_id: int
    scheduled_date: date
    day_order: int
    estimated_minutes: int
    status: PlanItemStatus
    completed_at: datetime | None


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    goal: str
    domain: str
    outcome_type: OutcomeType
    daily_minutes: int = Field(ge=5, le=240)
    timezone: str
    start_date: date
    target_date: date | None
    estimated_end_date: date
    status: PlanStatus
    version: int
    items: list[PlanItemResponse]


class ReplanRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
