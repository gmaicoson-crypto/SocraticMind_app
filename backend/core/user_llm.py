import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from core.ai_client import LLMProfile, register_custom_profile
from core.config import settings
from models import UserLLMProfile


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as error:
        raise ValueError("自定义模型密钥无法解密，请重新保存该模型") from error


def to_llm_profile(record: UserLLMProfile) -> LLMProfile:
    return LLMProfile(
        id=record.public_id,
        name=record.name,
        api_key=decrypt_api_key(record.api_key_encrypted),
        base_url=record.base_url,
        model=record.model,
        image_input=record.image_input,
        max_images=record.max_images,
        max_image_bytes=record.max_image_bytes,
        vision_token_budget=record.vision_token_budget,
    )


def load_user_profiles(db: Session, user_id: int) -> list[UserLLMProfile]:
    records = (
        db.query(UserLLMProfile)
        .filter(UserLLMProfile.user_id == user_id)
        .order_by(UserLLMProfile.created_at, UserLLMProfile.id)
        .all()
    )
    for record in records:
        register_custom_profile(to_llm_profile(record), user_id)
    return records


def get_owned_profile(db: Session, user_id: int, public_id: str) -> UserLLMProfile | None:
    if not public_id.startswith("custom:"):
        return None
    record_id = public_id.removeprefix("custom:")
    return (
        db.query(UserLLMProfile)
        .filter(UserLLMProfile.id == record_id, UserLLMProfile.user_id == user_id)
        .first()
    )
