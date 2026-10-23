from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from core.errors import ApiError
from models import LearnerMemory, Node, Topic
from models.enums import MemoryKind, MemorySource


def _validate_topic_scope(db: Session, user_id: int, topic_id: int | None) -> None:
    if topic_id is None:
        return
    exists = db.query(Topic.id).filter(Topic.id == topic_id, Topic.user_id == user_id).first()
    if exists is None:
        raise ApiError(status_code=404, code="TOPIC_NOT_FOUND", message="主题不存在")


def _owned_memory(db: Session, user_id: int, memory_id: int) -> LearnerMemory:
    memory = (
        db.query(LearnerMemory)
        .filter(LearnerMemory.id == memory_id, LearnerMemory.user_id == user_id)
        .first()
    )
    if memory is None:
        raise ApiError(status_code=404, code="MEMORY_NOT_FOUND", message="学习记忆不存在")
    return memory


def list_memories(
    db: Session,
    *,
    user_id: int,
    topic_id: int | None = None,
    kind: MemoryKind | str | None = None,
) -> list[LearnerMemory]:
    query = db.query(LearnerMemory).filter(LearnerMemory.user_id == user_id)
    if topic_id is not None:
        query = query.filter(LearnerMemory.topic_id == topic_id)
    if kind is not None:
        query = query.filter(LearnerMemory.kind == MemoryKind(kind).value)
    return query.order_by(LearnerMemory.updated_at.desc(), LearnerMemory.id.desc()).all()


def create_memory(
    db: Session,
    *,
    user_id: int,
    kind: MemoryKind | str,
    content: str,
    topic_id: int | None = None,
) -> LearnerMemory:
    _validate_topic_scope(db, user_id, topic_id)
    content = content.strip()
    if not content or len(content) > 300:
        raise ApiError(
            status_code=422,
            code="MEMORY_CONTENT_INVALID",
            message="记忆内容长度必须为 1 到 300 字",
        )
    memory = LearnerMemory(
        user_id=user_id,
        topic_id=topic_id,
        kind=MemoryKind(kind).value,
        content=content,
        source=MemorySource.USER.value,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def update_memory(
    db: Session,
    *,
    user_id: int,
    memory_id: int,
    updates: dict,
) -> LearnerMemory:
    memory = _owned_memory(db, user_id, memory_id)
    if "topic_id" in updates:
        _validate_topic_scope(db, user_id, updates["topic_id"])
        memory.topic_id = updates["topic_id"]
    if "kind" in updates:
        memory.kind = MemoryKind(updates["kind"]).value
    if "content" in updates:
        content = str(updates["content"]).strip()
        if not content or len(content) > 300:
            raise ApiError(
                status_code=422,
                code="MEMORY_CONTENT_INVALID",
                message="记忆内容长度必须为 1 到 300 字",
            )
        memory.content = content
    db.commit()
    db.refresh(memory)
    return memory


def delete_memory(db: Session, *, user_id: int, memory_id: int) -> None:
    memory = _owned_memory(db, user_id, memory_id)
    db.delete(memory)
    db.commit()


def select_relevant_memories(
    db: Session,
    *,
    user_id: int,
    topic_id: int | None = None,
    max_items: int = 20,
    max_characters: int = 3000,
) -> list[LearnerMemory]:
    query = db.query(LearnerMemory).filter(LearnerMemory.user_id == user_id)
    if topic_id is None:
        query = query.filter(LearnerMemory.topic_id.is_(None))
        ordering = [LearnerMemory.updated_at.desc(), LearnerMemory.id.desc()]
    else:
        query = query.filter(
            or_(LearnerMemory.topic_id == topic_id, LearnerMemory.topic_id.is_(None))
        )
        ordering = [
            case((LearnerMemory.topic_id == topic_id, 0), else_=1),
            LearnerMemory.updated_at.desc(),
            LearnerMemory.id.desc(),
        ]

    candidates = query.order_by(*ordering).limit(max_items).all()
    selected: list[LearnerMemory] = []
    used_characters = 0
    for memory in candidates:
        length = len(memory.content)
        if used_characters + length > max_characters:
            continue
        selected.append(memory)
        used_characters += length
    return selected


def upsert_assessment_memories(
    db: Session,
    *,
    user_id: int,
    node: Node,
    weaknesses: list[str],
    passed: bool,
    confidence: float,
) -> list[LearnerMemory]:
    entries: list[tuple[str, str]] = []
    if passed:
        entries.append((MemoryKind.STRENGTH.value, f"已通过“{node.label}”的正式评估"))
    else:
        effective_weaknesses = weaknesses or [f"“{node.label}”的评估尚未通过"]
        entries.extend(
            (MemoryKind.WEAKNESS.value, str(content)[:300]) for content in effective_weaknesses
        )

    memories: list[LearnerMemory] = []
    for kind, content in entries:
        memory = (
            db.query(LearnerMemory)
            .filter(
                LearnerMemory.user_id == user_id,
                LearnerMemory.topic_id == node.topic_id,
                LearnerMemory.kind == kind,
                LearnerMemory.source == MemorySource.ASSESSMENT.value,
                LearnerMemory.content == content,
            )
            .first()
        )
        if memory is None:
            memory = LearnerMemory(
                user_id=user_id,
                topic_id=node.topic_id,
                kind=kind,
                content=content,
                source=MemorySource.ASSESSMENT.value,
                confidence=confidence,
            )
            db.add(memory)
        else:
            memory.confidence = confidence
        memories.append(memory)
    return memories
