from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.avatars import choose_user_avatar


class User(Base):
    """用户表：存储账号基本信息及个性化学习设置（头像、每日目标、AI 风格等）。"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    avatar_grad = Column(
        String(255), default="linear-gradient(135deg,#e8c87a,#d4974a)"
    )  # 历史字段，保留旧数据；头像展示统一使用 avatar_url
    avatar_url = Column(String(500), nullable=False, default=choose_user_avatar)
    ai_avatar_url = Column(String(500), default="/avatars/AI/study/AI-male-1.webp", nullable=False)
    bio = Column(String(500), default="每一个问题都是通往掌握的一步")
    daily_goal = Column(Integer, default=5)  # 每日目标对话数
    ai_style = Column(String(50), default="标准")  # AI 教学风格：温和 / 标准 / 严格
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # cascade="all, delete" 确保注销账号时，关联的主题和节点一并级联删除
    topics = relationship("Topic", back_populates="user", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("LearnerMemory", back_populates="user", cascade="all, delete-orphan")
    study_plans = relationship("StudyPlan", back_populates="user", cascade="all, delete-orphan")
    assessment_attempts = relationship(
        "AssessmentAttempt", back_populates="user", cascade="all, delete-orphan"
    )
    mastery_events = relationship(
        "MasteryEvent", back_populates="user", cascade="all, delete-orphan"
    )
    llm_profiles = relationship(
        "UserLLMProfile", back_populates="user", cascade="all, delete-orphan"
    )
    archived_chat_activity = relationship(
        "ArchivedChatActivity", back_populates="user", cascade="all, delete-orphan"
    )
    archived_mastery = relationship(
        "ArchivedMastery", back_populates="user", cascade="all, delete-orphan"
    )
