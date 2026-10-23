from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.enums import MemoryKind, MemorySource


class MemoryCreate(BaseModel):
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=300)
    topic_id: int | None = Field(default=None, ge=1)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


class MemoryUpdate(BaseModel):
    kind: MemoryKind | None = None
    content: str | None = Field(default=None, min_length=1, max_length=300)
    topic_id: int | None = Field(default=None, ge=1)

    @field_validator("content")
    @classmethod
    def strip_optional_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value

    @model_validator(mode="after")
    def require_a_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int | None
    kind: MemoryKind
    content: str
    source: MemorySource
    confidence: float | None
    created_at: datetime
    updated_at: datetime


__all__ = ["MemoryCreate", "MemoryKind", "MemoryResponse", "MemorySource", "MemoryUpdate"]
