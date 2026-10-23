from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.errors import ApiError
from models import AssessmentAttempt, MasteryEvent, Node, StudyPlanItem, Topic
from models.enums import AssessmentStatus, MasterySource, PlanItemStatus


@dataclass(frozen=True)
class MasteryOperationResult:
    event_id: int | None
    node_id: int
    state: str
    refresh_required: bool = True


def _owned_node(db: Session, user_id: int, node_id: int) -> Node:
    node = (
        db.query(Node)
        .join(Topic, Node.topic_id == Topic.id)
        .filter(Node.id == node_id, Topic.user_id == user_id)
        .with_for_update()
        .first()
    )
    if node is None:
        raise ApiError(status_code=404, code="NODE_NOT_FOUND", message="节点不存在")
    return node


def _idempotent_result(db: Session, user_id: int, request_id: str) -> MasteryOperationResult | None:
    event = db.query(MasteryEvent).filter_by(user_id=user_id, request_id=request_id).first()
    if event is None:
        return None
    node = db.get(Node, event.node_id)
    return MasteryOperationResult(
        event_id=event.id,
        node_id=event.node_id,
        state=node.state if node is not None else event.to_state,
    )


def _all_topic_nodes_for_update(db: Session, topic_id: int) -> list[Node]:
    return (
        db.query(Node).filter(Node.topic_id == topic_id).order_by(Node.id).with_for_update().all()
    )


def _recompute_unmastered_states(nodes: list[Node]) -> None:
    mastered_keys = {node.node_key for node in nodes if node.state == "mastered"}
    for node in nodes:
        if node.state == "mastered":
            continue
        parents = {key.strip() for key in (node.parent_keys or "").split(",") if key.strip()}
        node.state = "available" if not parents or parents.issubset(mastered_keys) else "locked"


def record_mastery(
    db: Session,
    *,
    user_id: int,
    node_id: int,
    source: MasterySource | str,
    request_id: str,
    assessment_id: int | None = None,
) -> MasteryOperationResult:
    existing = _idempotent_result(db, user_id, request_id)
    if existing is not None:
        return existing

    source_value = MasterySource(source).value
    node = _owned_node(db, user_id, node_id)
    if node.state == "locked":
        raise ApiError(status_code=409, code="NODE_LOCKED", message="节点尚未解锁")
    if node.state == "mastered":
        latest = (
            db.query(MasteryEvent)
            .filter(MasteryEvent.user_id == user_id, MasteryEvent.node_id == node.id)
            .order_by(MasteryEvent.id.desc())
            .first()
        )
        return MasteryOperationResult(
            event_id=latest.id if latest else None,
            node_id=node.id,
            state=node.state,
        )

    attempt = None
    total_score = None
    confidence = None
    if source_value == MasterySource.ASSESSMENT.value:
        if assessment_id is not None:
            attempt = (
                db.query(AssessmentAttempt)
                .filter(
                    AssessmentAttempt.id == assessment_id,
                    AssessmentAttempt.user_id == user_id,
                    AssessmentAttempt.node_id == node.id,
                    AssessmentAttempt.status == AssessmentStatus.COMPLETED.value,
                )
                .first()
            )
        if attempt is None or attempt.total_score is None or attempt.evaluation_confidence is None:
            raise ApiError(
                status_code=409,
                code="ASSESSMENT_EVIDENCE_REQUIRED",
                message="评估掌握需要已完成的评分证据",
            )
        total_score = attempt.total_score
        confidence = attempt.evaluation_confidence
    elif assessment_id is not None:
        raise ApiError(
            status_code=422,
            code="ASSESSMENT_NOT_ALLOWED",
            message="仅评估掌握可以关联评估记录",
        )

    previous_state = node.state
    now = datetime.now(timezone.utc)
    node.state = "mastered"
    node.mastered_at = now
    node.mastery_source = source_value
    node.mastery_confidence = confidence

    nodes = _all_topic_nodes_for_update(db, node.topic_id)
    _recompute_unmastered_states(nodes)
    (
        db.query(StudyPlanItem)
        .filter(
            StudyPlanItem.node_id == node.id,
            StudyPlanItem.status == PlanItemStatus.PENDING.value,
        )
        .update(
            {
                StudyPlanItem.status: PlanItemStatus.COMPLETED.value,
                StudyPlanItem.completed_at: now,
            },
            synchronize_session=False,
        )
    )
    event = MasteryEvent(
        user_id=user_id,
        node_id=node.id,
        assessment_id=attempt.id if attempt else None,
        source=source_value,
        from_state=previous_state,
        to_state="mastered",
        confidence=confidence,
        total_score=total_score,
        request_id=request_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return MasteryOperationResult(event_id=event.id, node_id=node.id, state="mastered")


def revert_mastery(
    db: Session,
    *,
    user_id: int,
    node_id: int,
    request_id: str,
) -> MasteryOperationResult:
    existing = _idempotent_result(db, user_id, request_id)
    if existing is not None:
        return existing

    node = _owned_node(db, user_id, node_id)
    if node.state != "mastered":
        raise ApiError(status_code=409, code="NODE_NOT_MASTERED", message="节点尚未掌握")

    original_event = (
        db.query(MasteryEvent)
        .filter(
            MasteryEvent.user_id == user_id,
            MasteryEvent.node_id == node.id,
            MasteryEvent.to_state == "mastered",
        )
        .order_by(MasteryEvent.id.desc())
        .first()
    )
    previous_state = node.state
    node.state = "available"
    node.mastered_at = None
    node.mastery_source = None
    node.mastery_confidence = None

    nodes = _all_topic_nodes_for_update(db, node.topic_id)
    _recompute_unmastered_states(nodes)
    (
        db.query(StudyPlanItem)
        .filter(
            StudyPlanItem.node_id == node.id,
            StudyPlanItem.status == PlanItemStatus.COMPLETED.value,
        )
        .update(
            {
                StudyPlanItem.status: PlanItemStatus.PENDING.value,
                StudyPlanItem.completed_at: None,
            },
            synchronize_session=False,
        )
    )
    event = MasteryEvent(
        user_id=user_id,
        node_id=node.id,
        source=MasterySource.REVERT.value,
        from_state=previous_state,
        to_state=node.state,
        reverts_event_id=original_event.id if original_event else None,
        request_id=request_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return MasteryOperationResult(event_id=event.id, node_id=node.id, state=node.state)
