from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from .config import settings


def hash_password(password: str) -> str:
    """使用 bcrypt 对密码进行哈希，截取前 72 字节以避免 bcrypt 长度限制问题。"""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与数据库中存储的哈希是否匹配。"""
    pwd_bytes = plain.encode("utf-8")[:72]
    return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    """生成 JWT Access Token，过期时间由配置项 access_token_expire_minutes 控制。"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    """解码并验证 JWT，签名无效或已过期时返回 None。"""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        return None
