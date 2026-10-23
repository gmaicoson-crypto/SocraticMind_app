import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class UserLLMProfile(Base):
    """用户私有的 OpenAI 兼容模型配置；API Key 只保存加密后的密文。"""

    __tablename__ = "user_llm_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    base_url = Column(String(500), nullable=False)
    model = Column(String(200), nullable=False)
    image_input = Column(String(16), nullable=False, default="unknown", server_default="unknown")
    max_images = Column(Integer, nullable=False, default=5, server_default="5")
    max_image_bytes = Column(Integer, nullable=False, default=10485760, server_default="10485760")
    vision_token_budget = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="llm_profiles")

    __table_args__ = (Index("ix_user_llm_profiles_user_id", "user_id"),)

    @property
    def public_id(self) -> str:
        return f"custom:{self.id}"
