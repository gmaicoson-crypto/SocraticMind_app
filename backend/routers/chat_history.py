"""Additive mobile read routes; legacy history response shapes remain unchanged."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.database import get_db
from core.deps import get_current_user
from models import User
from schemas.chat_history import ConversationPage, MessagePage
from services.chat_history import conversations, session_messages


router = APIRouter()


def validate_cursor(before_id: int | None, snapshot_id: int | None):
    if before_id is not None and (snapshot_id is None or before_id > snapshot_id):
        raise HTTPException(status_code=422, detail="翻页需要原始快照和有效游标")


@router.get("/sessions", response_model=ConversationPage)
def list_conversations(
    mode: Literal["normal", "socratic"] = "normal",
    limit: int = Query(default=30, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
    snapshot_id: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Descending visible message IDs at a fixed upper bound; titles are current values."""
    validate_cursor(before_id, snapshot_id)
    return conversations(
        db,
        user_id=current_user.id,
        mode=mode,
        limit=limit,
        before_id=before_id,
        snapshot_id=snapshot_id,
    )


@router.get("/session-messages", response_model=MessagePage)
def list_session_messages(
    session_id: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
    snapshot_id: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Newest page first. Unknown / foreign sessions are indistinguishable empty pages."""
    validate_cursor(before_id, snapshot_id)
    if not session_id.strip():
        raise HTTPException(status_code=422, detail="会话 ID 不能为空")
    return session_messages(
        db,
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
        before_id=before_id,
        snapshot_id=snapshot_id,
    )
