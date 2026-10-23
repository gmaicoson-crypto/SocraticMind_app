from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class Topic(Base):
    """学习主题表：每个主题对应一张知识图谱，包含若干有依赖关系的节点。"""

    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    emoji = Column(String(10), default="📚")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # cascade="all, delete" 确保删除主题时，关联的所有节点一并级联删除
    nodes = relationship("Node", back_populates="topic", cascade="all, delete-orphan")
    user = relationship("User", back_populates="topics")
    agent_runs = relationship("AgentRun", back_populates="topic")
    memories = relationship("LearnerMemory", back_populates="topic", cascade="all, delete-orphan")
    study_plan = relationship(
        "StudyPlan", back_populates="topic", cascade="all, delete-orphan", uselist=False
    )
