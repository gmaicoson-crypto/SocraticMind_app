from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from core.ai_client import resolve_model_id
from core.database import get_db
from core.deps import get_current_user
from core.user_llm import load_user_profiles
from models import ChatMessage, ChatSessionTitle, User
from services.chat_titles import schedule_title

router = APIRouter(prefix="/api/chat/session-titles", tags=["chat"])


def title_response(row):
    return {
        "session_id": row.session_id,
        "title": row.title,
        "status": row.status,
        "retry_pending": row.status == "failed" and row.next_retry_at is not None,
    }


class TitleRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    mode: Literal["socratic", "normal"]
    message: str = Field(default="", max_length=4000)
    attachment_names: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(
        default_factory=list, max_length=9
    )
    model: str | None = Field(default=None, max_length=100)

    @field_validator("session_id")
    @classmethod
    def nonblank_session(cls, value):
        if not value.strip():
            raise ValueError("session_id must not be blank")
        return value.strip()


@router.post("")
def request_title(
    req: TitleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    source = req.message.strip()
    if req.attachment_names:
        source += "\n附件：" + "、".join(name[:255] for name in req.attachment_names)
    if not source.strip():
        raise HTTPException(status_code=400, detail="发送消息后才能生成标题")
    existing = (
        db.query(ChatSessionTitle).filter_by(user_id=user.id, session_id=req.session_id).first()
    )
    if existing is not None:
        if existing.mode != req.mode:
            raise HTTPException(status_code=409, detail="对话模式不一致")
        return title_response(existing)
    load_user_profiles(db, user.id)
    try:
        model_id = resolve_model_id(req.model, user_id=user.id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="所选模型不可用") from error
    row = schedule_title(
        db,
        user_id=user.id,
        session_id=req.session_id,
        mode=req.mode,
        source_text=source,
        model_id=model_id,
    )
    db.commit()
    return title_response(row)


@router.get("")
def get_titles(
    ids: list[str] = Query(max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        title_response(row)
        for row in db.query(ChatSessionTitle)
        .filter(
            ChatSessionTitle.user_id == user.id,
            ChatSessionTitle.session_id.in_(ids),
        )
        .all()
    ]


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=40)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class RenameSessionRequest(RenameRequest):
    session_id: str = Field(min_length=1, max_length=100)

    @field_validator("session_id")
    @classmethod
    def nonblank_session(cls, value):
        return TitleRequest.nonblank_session(value)


@router.put("")
def rename_session_title(
    req: RenameSessionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """JSON keeps opaque session IDs out of URL routing; legacy histories need no AI title job."""
    row = db.query(ChatSessionTitle).filter_by(user_id=user.id, session_id=req.session_id).first()
    if row is None:
        source = (
            db.query(ChatMessage.mode)
            .filter_by(user_id=user.id, session_id=req.session_id, message_type="chat")
            .order_by(ChatMessage.id.desc())
            .first()
        )
        if source is None:
            raise HTTPException(status_code=404, detail="对话不存在，请先发送消息")
        if source.mode not in {"normal", "socratic"}:
            raise HTTPException(status_code=409, detail="对话模式不一致")
        # Reuse the unique-row/savepoint behavior, then make it manual before this transaction commits.
        schedule_title(
            db,
            user_id=user.id,
            session_id=req.session_id,
            mode=source.mode,
            source_text="",
            model_id="",
        )
    return rename_title(req.session_id, req, user, db)


@router.put("/{session_id}")
def rename_title(
    session_id: str,
    req: RenameRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changed = (
        db.query(ChatSessionTitle)
        .filter_by(user_id=user.id, session_id=session_id)
        .update(
            {
                "title": req.title,
                "status": "manual",
                "source_text": None,
                "lease_token": None,
                "lease_until": None,
                "next_retry_at": None,
            },
            synchronize_session=False,
        )
    )
    if not changed:
        raise HTTPException(status_code=404, detail="对话不存在，请先发送消息")
    db.commit()
    return title_response(
        db.query(ChatSessionTitle)
        .filter_by(user_id=user.id, session_id=session_id)
        .populate_existing()
        .one()
    )
