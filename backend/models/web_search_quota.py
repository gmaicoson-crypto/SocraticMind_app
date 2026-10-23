from sqlalchemy import Column, Date, Integer, String

from core.database import Base


class WebSearchQuota(Base):
    """Daily query reservations survive chat deletion and coordinate all workers."""

    __tablename__ = "web_search_quotas"

    scope = Column(String(80), primary_key=True)
    day = Column(Date, primary_key=True)
    used_queries = Column(Integer, nullable=False, default=0)
