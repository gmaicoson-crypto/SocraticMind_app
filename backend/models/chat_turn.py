from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, JSON
from sqlalchemy.sql import func

from core.database import Base


class ChatTurn(Base):
    """A generation attempt with a stable user-message/answer relationship."""

    __tablename__ = "chat_turns"

    id = Column(Integer, primary_key=True)
    chat_session_id = Column(
        Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(String(100), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    user_message_id = Column(
        Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    ai_message_id = Column(
        Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    regenerate_message_id = Column(
        Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String(20), default="generating", nullable=False)
    model_id = Column(String(100), nullable=False)
    node_key = Column(String(100), nullable=False)
    kind = Column(String(30), default="qa", nullable=False)
    generation_token = Column(String(36), nullable=False)
    source_version = Column(Integer, nullable=False)
    error_code = Column(String(80), nullable=True)
    preparation_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_chat_turns_user_request", "user_id", "request_id", unique=True),
        Index("ix_chat_turns_session_status_id", "chat_session_id", "status", "id"),
        Index("ix_chat_turns_ai_message", "ai_message_id"),
        Index("ix_chat_turns_user_message", "user_message_id"),
        {"sqlite_autoincrement": True},
    )
