from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base
from .enums import AssessmentStatus


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), default=AssessmentStatus.ACTIVE.value, nullable=False)
    questions_json = Column(JSON, default=list, nullable=False)
    answers_json = Column(JSON, default=list, nullable=False)
    rubrics_json = Column(JSON, default=list, nullable=False)
    scores_json = Column(JSON, nullable=True)
    total_score = Column(Integer, nullable=True)
    evaluation_confidence = Column(Float, nullable=True)
    critical_misconception = Column(Boolean, nullable=True)
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="assessment_attempts")
    node = relationship("Node", back_populates="assessment_attempts")
    run = relationship("AgentRun", back_populates="assessment_attempt")
    mastery_events = relationship("MasteryEvent", back_populates="assessment")

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_assessment_attempts_run_id"),
        Index("ix_assessment_user_node_status", "user_id", "node_id", "status"),
    )
