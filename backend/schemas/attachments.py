from pydantic import BaseModel, Field
from typing import Literal


class CoverageConfirmation(BaseModel):
    revision: int = Field(ge=1)


class AttachmentSummary(BaseModel):
    id: str
    name: str
    mime_type: str
    size: int
    kind: Literal["image", "document"]
    status: Literal["pending", "processing", "ready", "needs_confirmation", "failed", "deleted"]
    pages: int | None = None
    width: int | None = None
    height: int | None = None
    revision: int
    warnings: list[str] = Field(default_factory=list)
    coverage: dict | None = None
    accepted_coverage: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
