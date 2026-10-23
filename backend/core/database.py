from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings

# pool_pre_ping=True：每次从连接池取连接前先发一个轻量探活，避免使用已断开的连接
engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入用的数据库会话生成器，请求结束后自动关闭连接。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
