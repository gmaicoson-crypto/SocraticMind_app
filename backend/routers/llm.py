import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from core.ai_client import register_custom_profile, remove_custom_profile
from core.config import LLMImageCapabilities, settings
from core.database import get_db
from core.deps import get_current_user
from core.user_llm import encrypt_api_key, get_owned_profile, to_llm_profile
from models import User, UserLLMProfile


router = APIRouter(prefix="/api/llm", tags=["LLM"])


@router.get("/models")
def get_llm_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回可选的环境模型与当前用户模型，不返回环境连接信息或凭据。"""
    environment_models = [
        {
            "id": profile.id,
            "name": profile.name,
            "model": profile.model,
            "source": "environment",
            **profile.model_dump(include=set(LLMImageCapabilities.model_fields)),
        }
        for profile in settings.llm_profiles
    ]
    records = (
        db.query(UserLLMProfile)
        .filter(UserLLMProfile.user_id == current_user.id)
        .order_by(UserLLMProfile.created_at, UserLLMProfile.id)
        .all()
    )
    return {"models": environment_models + [_custom_model_response(record) for record in records]}


class CustomModelRequest(LLMImageCapabilities):
    name: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1, max_length=1000)
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)

    @field_validator("name", "api_key", "base_url", "model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not re.fullmatch(r"https?://[^\s]+", value):
            raise ValueError("服务地址必须是 http:// 或 https:// 地址")
        return value.rstrip("/")


class CustomModelUpdateRequest(LLMImageCapabilities):
    name: str = Field(min_length=1, max_length=100)
    api_key: str | None = Field(default=None, max_length=1000)
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)

    @field_validator("name", "base_url", "model")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("api_key")
    @classmethod
    def strip_optional_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not re.fullmatch(r"https?://[^\s]+", value):
            raise ValueError("服务地址必须是 http:// 或 https:// 地址")
        return value.rstrip("/")


def _custom_model_response(record: UserLLMProfile) -> dict:
    return {
        "id": record.public_id,
        "name": record.name,
        "model": record.model,
        "base_url": record.base_url,
        "source": "custom",
        **{key: getattr(record, key) for key in LLMImageCapabilities.model_fields},
    }


@router.post("/models", status_code=status.HTTP_201_CREATED)
def create_custom_model(
    request: CustomModelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = UserLLMProfile(
        user_id=current_user.id,
        name=request.name,
        api_key_encrypted=encrypt_api_key(request.api_key),
        base_url=request.base_url,
        model=request.model,
        **request.model_dump(include=set(LLMImageCapabilities.model_fields)),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    register_custom_profile(to_llm_profile(record), current_user.id)
    return _custom_model_response(record)


@router.put("/models/{model_id}")
def update_custom_model(
    model_id: str,
    request: CustomModelUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_owned_profile(db, current_user.id, model_id)
    if record is None:
        raise HTTPException(status_code=404, detail="自定义模型不存在")
    record.name = request.name
    record.base_url = request.base_url
    record.model = request.model
    for key in LLMImageCapabilities.model_fields:
        if key in request.model_fields_set:
            setattr(record, key, getattr(request, key))
    if request.api_key is not None:
        record.api_key_encrypted = encrypt_api_key(request.api_key)
    db.commit()
    db.refresh(record)
    register_custom_profile(to_llm_profile(record), current_user.id)
    return _custom_model_response(record)


@router.delete("/models/{model_id}")
def delete_custom_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_owned_profile(db, current_user.id, model_id)
    if record is None:
        raise HTTPException(status_code=404, detail="自定义模型不存在")
    remove_custom_profile(record.public_id)
    db.delete(record)
    db.commit()
    return {"message": "自定义模型已删除"}
