from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class MasteryEvent(Base):
    __tablename__ = "mastery_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    assessment_id = Column(
        Integer, ForeignKey("assessment_attempts.id", ondelete="SET NULL"), nullable=True
    )
    source = Column(String(30), nullable=False)
    from_state = Column(String(20), nullable=False)
    to_state = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=True)
    total_score = Column(Integer, nullable=True)
    reverts_event_id = Column(
        Integer, ForeignKey("mastery_events.id", ondelete="SET NULL"), nullable=True
    )
    request_id = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="mastery_events")
    node = relationship("Node", back_populates="mastery_events")
    assessment = relationship("AssessmentAttempt", back_populates="mastery_events")
    reverts_event = relationship("MasteryEvent", remote_side=[id], backref="reverted_by")

    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_mastery_user_request"),
        Index("ix_mastery_events_node_created", "node_id", "created_at"),
    )
