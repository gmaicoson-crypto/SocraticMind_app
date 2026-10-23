from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.sql import func

from core.database import Base


class ChatSession(Base):
    """Persistent context state; append-only turns do not invalidate a summary."""

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(100), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=True)
    mode = Column(String(50), nullable=False)
    content_version = Column(Integer, default=1, nullable=False)
    summary_json = Column(JSON, nullable=True)
    summary_through_turn_id = Column(Integer, nullable=True)
    summary_source_version = Column(Integer, nullable=True)
    summary_version = Column(Integer, default=1, nullable=False)
    summary_status = Column(String(20), default="idle", nullable=False)
    summary_model = Column(String(100), nullable=True)
    summary_lease_token = Column(String(36), nullable=True)
    summary_lease_until = Column(DateTime(timezone=True), nullable=True)
    summary_attempts = Column(Integer, default=0, nullable=False)
    summary_next_retry_at = Column(DateTime(timezone=True), nullable=True)
    active_request_id = Column(String(100), nullable=True)
    generation_lease_token = Column(String(36), nullable=True)
    generation_lease_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_chat_sessions_user_session", "user_id", "session_id", unique=True),
        Index("ix_chat_sessions_user_topic_updated", "user_id", "topic_id", "updated_at"),
        Index("ix_chat_sessions_summary_work", "summary_status", "summary_next_retry_at"),
        {"sqlite_autoincrement": True},
    )
