from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.database import get_db
from core.deps import get_current_user
from models import User
from schemas.plan import ReplanRequest
from services.plans import (
    get_today_plan,
    get_topic_plan,
    replan,
    serialize_plan,
)


router = APIRouter(tags=["学习计划"])


@router.get("/api/plans/today")
def read_today_plan(
    timezone: str | None = Query(default=None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_today_plan(db, user_id=current_user.id, timezone_name=timezone)


@router.get("/api/topics/{topic_id}/plan")
def read_topic_plan(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_plan(get_topic_plan(db, user_id=current_user.id, topic_id=topic_id))


@router.post("/api/plans/{plan_id}/replan")
def replan_topic(
    plan_id: int,
    request: ReplanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_plan(
        replan(
            db,
            user_id=current_user.id,
            plan_id=plan_id,
            request_id=request.request_id,
            timezone_name=request.timezone,
        )
    )
