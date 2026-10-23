from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index
from sqlalchemy.sql import func
from core.database import Base


class EmailCode(Base):
    """邮箱验证码表：注册和重置密码时生成，有效期 10 分钟，使用后标记为 used 防止重放攻击。"""

    __tablename__ = "email_codes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    code = Column(String(10), nullable=False)
    purpose = Column(String(20), nullable=False)  # register / reset
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 校验时按 (email, purpose) 取最新未过期未使用的一条，复合索引加速查询
    __table_args__ = (Index("ix_email_codes_email_purpose", "email", "purpose"),)
