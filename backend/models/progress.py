from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Index, JSON
from sqlalchemy.sql import func
from core.database import Base


class ChatMessage(Base):
    """对话消息表：记录用户与 AI 的每一条消息，用于历史回溯和学习统计。"""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # 会话按主题 topic_id 归属
    topic_id = Column(Integer, nullable=True, index=True)
    # session_id 用于重建和精确删除单个会话。
    session_id = Column(String(100), nullable=False, index=True)
    node_key = Column(String(100), nullable=False)
    role = Column(String(10), nullable=False)  # "user" 或 "ai"
    content = Column(Text, nullable=False)
    mode = Column(String(50), default="socratic")  # socratic / normal
    message_type = Column(String(30), default="chat", nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 热力图、连续打卡、活跃时段统计均按 user_id + created_at 范围过滤
    __table_args__ = (
        Index("ix_chat_user_created", "user_id", "created_at"),
        Index(
            "ix_chat_user_session_type_id",
            "user_id",
            "session_id",
            "message_type",
            "id",
        ),
        Index("ix_chat_role", "role"),
        Index("ix_chat_mode", "mode"),
    )


class LearningRecord(Base):
    """学习打卡记录表：每天学习至少一次即打卡一条，用于计算连续学习天数（streak）。"""

    __tablename__ = "learning_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(String(10), nullable=False)  # 格式 "YYYY-MM-DD"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # unique=True 保证同一用户同一天只有一条记录，防止并发重复插入
    __table_args__ = (Index("ix_lr_user_date", "user_id", "date", unique=True),)
