"""Read projections shared by legacy history and bounded mobile pagination."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    role: str
    content: str
    node_key: str = ""
    mode: str = ""
    topic_id: int | None = None
    session_id: str
    message_type: str = "chat"
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_json")
    created_at: datetime | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    session_id: str
    mode: str
    topic_id: int | None
    node_key: str
    last_message_id: int
    last_role: str
    preview: str
    updated_at: datetime | None
    title: str | None
    title_status: str | None


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    snapshot_id: int
    next_before_id: int | None


class MessagePage(BaseModel):
    items: list[HistoryResponse]
    snapshot_id: int
    next_before_id: int | None
