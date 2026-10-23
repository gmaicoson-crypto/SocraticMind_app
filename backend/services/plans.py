from datetime import date

from sqlalchemy.orm import Session, selectinload

from core.errors import ApiError
from models import Node, StudyPlan, StudyPlanItem, Topic
from models.enums import PlanItemStatus
from services.planning import PlanItemDraft, replan_schedule, today_in_timezone


def _plan_not_found() -> ApiError:
    return ApiError(status_code=404, code="PLAN_NOT_FOUND", message="学习计划不存在")


def get_topic_plan(db: Session, *, user_id: int, topic_id: int) -> StudyPlan:
    plan = (
        db.query(StudyPlan)
        .options(selectinload(StudyPlan.items).joinedload(StudyPlanItem.node))
        .filter(StudyPlan.user_id == user_id, StudyPlan.topic_id == topic_id)
        .first()
    )
    if plan is None:
        raise _plan_not_found()
    return plan


def get_plan_by_id(db: Session, *, user_id: int, plan_id: int) -> StudyPlan:
    plan = (
        db.query(StudyPlan)
        .populate_existing()
        .options(selectinload(StudyPlan.items).joinedload(StudyPlanItem.node))
        .filter(StudyPlan.user_id == user_id, StudyPlan.id == plan_id)
        .first()
    )
    if plan is None:
        raise _plan_not_found()
    return plan


def serialize_plan(plan: StudyPlan) -> dict:
    items = sorted(plan.items, key=lambda item: (item.scheduled_date, item.day_order, item.id))
    return {
        "id": plan.id,
        "topic_id": plan.topic_id,
        "goal": plan.goal,
        "domain": plan.domain,
        "outcome_type": plan.outcome_type,
        "daily_minutes": plan.daily_minutes,
        "timezone": plan.timezone,
        "start_date": plan.start_date,
        "target_date": plan.target_date,
        "estimated_end_date": plan.estimated_end_date,
        "status": plan.status,
        "version": plan.version,
        "will_miss_target": bool(plan.target_date and plan.estimated_end_date > plan.target_date),
        "total_minutes": sum(item.estimated_minutes for item in items),
        "completed_minutes": sum(
            item.estimated_minutes
            for item in items
            if item.status == PlanItemStatus.COMPLETED.value
        ),
        "items": [
            {
                "id": item.id,
                "node_id": item.node_id,
                "node_key": item.node.node_key,
                "node_label": item.node.label,
                "scheduled_date": item.scheduled_date,
                "day_order": item.day_order,
                "estimated_minutes": item.estimated_minutes,
                "status": item.status,
                "completed_at": item.completed_at,
            }
            for item in items
        ],
    }


def get_today_plan(db: Session, *, user_id: int, timezone_name: str | None) -> dict:
    current_date, effective_timezone = today_in_timezone(timezone_name)
    rows = (
        db.query(StudyPlanItem, StudyPlan, Topic, Node)
        .join(StudyPlan, StudyPlanItem.plan_id == StudyPlan.id)
        .join(Topic, StudyPlan.topic_id == Topic.id)
        .join(Node, StudyPlanItem.node_id == Node.id)
        .filter(StudyPlan.user_id == user_id, StudyPlan.status == "active")
        .order_by(StudyPlanItem.scheduled_date, StudyPlanItem.day_order, StudyPlanItem.id)
        .all()
    )

    grouped: dict[str, dict[tuple[int, int, date], dict]] = {
        "today": {},
        "overdue": {},
        "upcoming": {},
    }
    for item, plan, topic, node in rows:
        if item.scheduled_date < current_date:
            if item.status == PlanItemStatus.COMPLETED.value:
                continue
            section = "overdue"
        elif item.scheduled_date == current_date:
            section = "today"
        else:
            section = "upcoming"
        key = (plan.id, node.id, item.scheduled_date)
        aggregate = grouped[section].setdefault(
            key,
            {
                "plan_id": plan.id,
                "topic_id": topic.id,
                "topic_title": topic.title,
                "topic_emoji": topic.emoji,
                "node_id": node.id,
                "node_key": node.node_key,
                "node_label": node.label,
                "scheduled_date": item.scheduled_date,
                "estimated_minutes": 0,
                "status": item.status,
                "item_ids": [],
                "day_order": item.day_order,
            },
        )
        aggregate["estimated_minutes"] += item.estimated_minutes
        aggregate["item_ids"].append(item.id)
        if item.status != PlanItemStatus.COMPLETED.value:
            aggregate["status"] = PlanItemStatus.PENDING.value

    result = {
        section: list(grouped[section].values()) for section in ("today", "overdue", "upcoming")
    }
    result.update(
        {
            "date": current_date,
            "effective_timezone": effective_timezone,
            "replan_suggested": bool(result["overdue"]),
        }
    )
    return result


def replan(
    db: Session,
    *,
    user_id: int,
    plan_id: int,
    request_id: str,
    timezone_name: str | None = None,
) -> StudyPlan:
    plan = (
        db.query(StudyPlan)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == user_id)
        .with_for_update()
        .first()
    )
    if plan is None:
        raise _plan_not_found()
    if plan.last_request_id == request_id:
        return get_plan_by_id(db, user_id=user_id, plan_id=plan.id)

    nodes = db.query(Node).filter(Node.topic_id == plan.topic_id).order_by(Node.id).all()
    items = (
        db.query(StudyPlanItem)
        .filter(StudyPlanItem.plan_id == plan.id)
        .order_by(StudyPlanItem.id)
        .all()
    )
    node_key_by_id = {node.id: node.node_key for node in nodes}
    completed = [
        PlanItemDraft(
            node_key=node_key_by_id[item.node_id],
            scheduled_date=item.scheduled_date,
            day_order=item.day_order,
            estimated_minutes=item.estimated_minutes,
            status=item.status,
            source_id=item.id,
        )
        for item in items
        if item.status == PlanItemStatus.COMPLETED.value
    ]
    graph = [
        {
            "key": node.node_key,
            "parent_keys": [
                key.strip() for key in (node.parent_keys or "").split(",") if key.strip()
            ],
            "estimated_minutes": node.estimated_minutes,
        }
        for node in nodes
    ]
    current_date, effective_timezone = today_in_timezone(timezone_name or plan.timezone)
    result = replan_schedule(
        graph,
        daily_minutes=plan.daily_minutes,
        timezone=effective_timezone,
        existing_items=completed,
        today=current_date,
        target_date=plan.target_date,
        skip_node_keys={node.node_key for node in nodes if node.state == "mastered"},
    )

    (
        db.query(StudyPlanItem)
        .filter(
            StudyPlanItem.plan_id == plan.id,
            StudyPlanItem.status == PlanItemStatus.PENDING.value,
        )
        .delete(synchronize_session="fetch")
    )
    node_id_by_key = {node.node_key: node.id for node in nodes}
    for draft in result.items:
        if draft.source_id is not None:
            continue
        db.add(
            StudyPlanItem(
                plan_id=plan.id,
                node_id=node_id_by_key[draft.node_key],
                scheduled_date=draft.scheduled_date,
                day_order=draft.day_order,
                estimated_minutes=draft.estimated_minutes,
                status=PlanItemStatus.PENDING.value,
            )
        )
    plan.timezone = result.effective_timezone
    plan.estimated_end_date = result.estimated_end_date
    plan.version += 1
    plan.last_request_id = request_id
    db.commit()
    return get_plan_by_id(db, user_id=user_id, plan_id=plan.id)
