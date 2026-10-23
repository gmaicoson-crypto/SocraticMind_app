"""Private attachments, immutable message bindings and recoverable cleanup work."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.sql import func

from core.database import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_upload_id = Column(String(100), nullable=False)
    draft_session_id = Column(String(100), nullable=False)
    session_id = Column(String(100), nullable=True)
    topic_id = Column(Integer, nullable=True)
    mode = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    mime_type = Column(String(120), nullable=False)
    kind = Column(String(20), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(255), nullable=False)
    preview_key = Column(String(255), nullable=True)
    image_key = Column(String(255), nullable=True)
    status = Column(String(30), nullable=False, default="pending")
    pages = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    warnings = Column(JSON, nullable=False, default=list)
    coverage = Column(JSON, nullable=True)
    accepted_coverage = Column(JSON, nullable=True)
    accepted_revision = Column(Integer, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(String(500), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_attachment_upload", "user_id", "client_upload_id", unique=True),
        Index("ix_attachment_work", "status", "next_retry_at"),
        Index("ix_attachment_scope", "user_id", "session_id"),
        Index("ix_attachment_expiry", "status", "expires_at"),
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    user_message_id = Column(
        Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True
    )
    attachment_id = Column(
        String(36), ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True
    )
    position = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    accepted_coverage = Column(JSON, nullable=True)

    __table_args__ = (
        Index("uq_message_attachment_position", "user_message_id", "position", unique=True),
        Index("uq_attachment_message", "attachment_id", unique=True),
    )


class AttachmentChunk(Base):
    __tablename__ = "attachment_chunks"

    attachment_id = Column(
        String(36), ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True
    )
    revision = Column(Integer, primary_key=True)
    chunk_id = Column(String(64), primary_key=True)
    position = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    locator = Column(JSON, nullable=False)
    block_type = Column(String(30), nullable=False)
    title_path = Column(JSON, nullable=False, default=list)
    asset_refs = Column(JSON, nullable=False, default=list)

    __table_args__ = (Index("ix_attachment_chunk_order", "attachment_id", "revision", "position"),)


class AttachmentCleanup(Base):
    """No user foreign key: deleting an account must not erase cleanup evidence."""

    __tablename__ = "attachment_cleanup"
    id = Column(String(36), primary_key=True)
    storage_prefix = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AttachmentWorkerSlot(Base):
    __tablename__ = "attachment_worker_slots"
    id = Column(Integer, primary_key=True)
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
