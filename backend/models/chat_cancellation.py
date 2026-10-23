from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from core.database import Base


class ChatCancellation(Base):
    """A durable stop intent, including requests that have not created a turn yet."""

    __tablename__ = "chat_cancellations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(String(100), nullable=False)
    session_id = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_chat_cancellations_user_request", "user_id", "request_id", unique=True),
    )
