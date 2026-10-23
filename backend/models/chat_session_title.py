from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from core.database import Base


class ChatSessionTitle(Base):
    """Titles also cover learning onboarding, before a chat context exists."""

    __tablename__ = "chat_session_titles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(100), nullable=False)
    mode = Column(String(50), nullable=False)
    title = Column(String(40), nullable=True)
    source_text = Column(Text, nullable=True)
    model_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_chat_session_titles_user_session", "user_id", "session_id", unique=True),
        Index("ix_chat_session_titles_work", "status", "next_retry_at"),
    )
