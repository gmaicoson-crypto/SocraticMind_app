from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class Node(Base):
    """知识图谱节点表：每个节点属于某个主题，在图谱中有坐标和学习状态。"""

    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False, index=True)
    node_key = Column(String(100), nullable=False)  # 前端用的唯一标识，如 "py-basics"
    label = Column(String(200), nullable=False)
    sub = Column(String(500), default="")  # 副标题，通常为英文描述
    state = Column(String(20), default="locked", index=True)  # locked / available / mastered
    x = Column(Float, default=0)  # SVG 画布横坐标
    y = Column(Float, default=0)  # SVG 画布纵坐标
    parent_keys = Column(String(500), default="")  # 逗号分隔的父节点 key，无父节点则为空
    mastered_at = Column(DateTime(timezone=True), nullable=True)
    estimated_minutes = Column(Integer, default=30, nullable=False)
    mastery_source = Column(String(30), nullable=True)
    mastery_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    topic = relationship("Topic", back_populates="nodes")
    plan_items = relationship("StudyPlanItem", back_populates="node", cascade="all, delete-orphan")
    assessment_attempts = relationship(
        "AssessmentAttempt", back_populates="node", cascade="all, delete-orphan"
    )
    mastery_events = relationship(
        "MasteryEvent", back_populates="node", cascade="all, delete-orphan"
    )

    # 复合索引覆盖"按主题 + 状态过滤"的高频查询（统计已掌握节点数、解锁逻辑等）
    __table_args__ = (Index("ix_nodes_topic_state", "topic_id", "state"),)
