import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base
from .enums import AgentRunStatus


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(100), nullable=True)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    run_type = Column(String(30), nullable=False)
    status = Column(String(30), default=AgentRunStatus.COLLECTING.value, nullable=False)
    version = Column(Integer, default=0, nullable=False)
    state_json = Column(JSON, default=dict, nullable=False)
    result_json = Column(JSON, nullable=True)
    model = Column(String(100), nullable=True)
    token_usage = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    error_code = Column(String(80), nullable=True)
    retryable = Column(Boolean, nullable=True)
    request_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="agent_runs")
    topic = relationship("Topic", back_populates="agent_runs")
    assessment_attempt = relationship(
        "AssessmentAttempt",
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_agent_runs_user_status", "user_id", "status"),
        Index("ix_agent_runs_topic_id", "topic_id"),
    )
