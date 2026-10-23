from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base
from .enums import PlanItemStatus, PlanStatus


class StudyPlan(Base):
    __tablename__ = "study_plans"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    goal = Column(String(500), nullable=False)
    domain = Column(String(100), nullable=False)
    outcome_type = Column(String(30), nullable=False)
    daily_minutes = Column(Integer, nullable=False)
    timezone = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    target_date = Column(Date, nullable=True)
    estimated_end_date = Column(Date, nullable=False)
    status = Column(String(30), default=PlanStatus.ACTIVE.value, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    last_request_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="study_plans")
    topic = relationship("Topic", back_populates="study_plan")
    items = relationship("StudyPlanItem", back_populates="plan", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("topic_id", name="uq_study_plans_topic_id"),
        Index("ix_study_plans_user_status", "user_id", "status"),
    )


class StudyPlanItem(Base):
    __tablename__ = "study_plan_items"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    day_order = Column(Integer, nullable=False)
    estimated_minutes = Column(Integer, nullable=False)
    status = Column(String(30), default=PlanItemStatus.PENDING.value, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("StudyPlan", back_populates="items")
    node = relationship("Node", back_populates="plan_items")

    __table_args__ = (
        UniqueConstraint("plan_id", "node_id", "scheduled_date", name="uq_plan_node_date"),
        Index("ix_plan_items_plan_date_status", "plan_id", "scheduled_date", "status"),
        Index("ix_plan_items_node_id", "node_id"),
    )
