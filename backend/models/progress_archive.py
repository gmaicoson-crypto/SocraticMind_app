from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship


class ArchivedChatActivity(Base):
    """Conversation counts retained after the source messages are deleted."""

    __tablename__ = "archived_chat_activity"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day = Column(String(10), nullable=False)
    hour = Column(Integer, nullable=False)
    count = Column(Integer, nullable=False)

    user = relationship("User", back_populates="archived_chat_activity")

    __table_args__ = (
        Index("ix_archived_chat_user_day", "user_id", "day"),
        Index("ix_archived_chat_user_hour", "user_id", "hour"),
    )


class ArchivedMastery(Base):
    """Completed learning outcomes retained after a topic is deleted."""

    __tablename__ = "archived_mastery"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(200), nullable=False)
    topic_title = Column(String(200), nullable=False)
    mastered_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="archived_mastery")

    __table_args__ = (Index("ix_archived_mastery_user_time", "user_id", "mastered_at"),)
