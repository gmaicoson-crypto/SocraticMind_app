from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class LearnerMemory(Base):
    __tablename__ = "learner_memories"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(30), nullable=False)
    content = Column(String(300), nullable=False)
    source = Column(String(30), nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="memories")
    topic = relationship("Topic", back_populates="memories")

    __table_args__ = (Index("ix_learner_memories_user_topic_kind", "user_id", "topic_id", "kind"),)
