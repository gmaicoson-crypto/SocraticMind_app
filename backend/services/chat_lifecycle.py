"""Short database transactions around generation; no lock spans an LLM call."""

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.errors import ApiError
from models import ChatCancellation, ChatMessage, ChatSession, ChatTurn
from services.chat_message_metadata import TERMINAL_STATUSES, usage_metadata, web_metadata
from services.web_search import empty_web_snapshot
from services.attachments.service import validate_for_message, bind_to_message
from services.chat_regeneration import regeneration_question

GENERATION_LEASE_SECONDS = 360


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _error(code: str, message: str, status: int = 409) -> ApiError:
    return ApiError(status_code=status, code=code, message=message, retryable=False)


@dataclass
class StartedChatTurn:
    session: ChatSession
    turn: ChatTurn
    user_message: ChatMessage
    ai_message: ChatMessage
    replayed: bool = False


def get_chat_turn(db: Session, *, user_id: int, request_id: str) -> ChatTurn | None:
    return (
        db.query(ChatTurn)
        .filter_by(user_id=user_id, request_id=request_id)
        .populate_existing()
        .one_or_none()
    )


def is_chat_cancelled(db: Session, *, user_id: int, request_id: str) -> bool:
    return (
        db.query(ChatCancellation.id).filter_by(user_id=user_id, request_id=request_id).first()
        is not None
    )


def _replay(db: Session, turn: ChatTurn, fingerprint: str) -> StartedChatTurn:
    if turn.request_fingerprint != fingerprint:
        raise _error("CHAT_REQUEST_CONFLICT", "请求标识已用于不同内容，请重新发送")
    session = db.get(ChatSession, turn.chat_session_id)
    user_message = db.get(ChatMessage, turn.user_message_id) if turn.user_message_id else None
    ai_message = db.get(ChatMessage, turn.ai_message_id) if turn.ai_message_id else None
    if (
        session is None
        or user_message is None
        or ai_message is None
        or turn.status in {"deleted", "superseded"}
    ):
        raise _error("CHAT_REQUEST_DELETED", "该请求的消息已删除或替换，请重新发送")
    deadline = session.generation_lease_until
    if (
        turn.status == "generating"
        and deadline is not None
        and deadline.replace(tzinfo=timezone.utc) < utcnow()
    ):
        changed = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == session.id,
                ChatSession.active_request_id == turn.request_id,
                ChatSession.generation_lease_token == turn.generation_token,
                ChatSession.generation_lease_until < utcnow(),
            )
            .update(
                {
                    "active_request_id": None,
                    "generation_lease_token": None,
                    "generation_lease_until": None,
                },
                synchronize_session=False,
            )
        )
        if changed:
            _mark_interrupted(db, turn, "GENERATION_LEASE_EXPIRED")
            db.commit()
        else:
            db.rollback()
            db.refresh(turn)
    return StartedChatTurn(session, turn, user_message, ai_message, True)


def recover_chat_turn(db: Session, *, user_id: int, request_id: str) -> ChatTurn:
    """Observe a persisted request without starting work; expire abandoned leases."""
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is None:
        raise _error("CHAT_REQUEST_NOT_FOUND", "请求不存在", 404)
    return _replay(db, turn, turn.request_fingerprint).turn


def _invalidate_summary_values() -> dict:
    return {
        "content_version": ChatSession.content_version + 1,
        "summary_json": None,
        "summary_through_turn_id": None,
        "summary_source_version": None,
        "summary_status": "pending",
        "summary_lease_token": None,
        "summary_lease_until": None,
        "summary_attempts": 0,
        "summary_next_retry_at": None,
    }


def _mark_interrupted(db: Session, turn: ChatTurn, code: str) -> None:
    turn.status = "interrupted"
    turn.error_code = code
    turn.finished_at = utcnow()
    message = db.get(ChatMessage, turn.ai_message_id) if turn.ai_message_id else None
    if message is not None:
        message.metadata_json = {
            **(message.metadata_json or {}),
            **web_metadata(message, message.content, status="interrupted", error_code=code),
            "status": "interrupted",
            "error_code": code,
        }


def _attachment_input(db, *, user_id, session_id, mode, topic_id, ids, regenerate_message_id):
    """Freeze immutable resource revisions, including the original question on retry."""
    from models.attachment import Attachment, MessageAttachment

    ids = list(ids or [])
    if len(ids) != len(set(ids)):
        raise _error("ATTACHMENT_DUPLICATE", "同一附件不能重复添加", 422)
    if regenerate_message_id is not None:
        answer = (
            db.query(ChatMessage)
            .filter_by(
                id=regenerate_message_id,
                user_id=user_id,
                session_id=session_id,
                mode=mode,
                topic_id=topic_id,
                role="ai",
            )
            .one_or_none()
        )
        original_id = (answer.metadata_json or {}).get("user_message_id") if answer else None
        original_ids = (
            [
                row.attachment_id
                for row in db.query(MessageAttachment)
                .filter_by(user_message_id=original_id)
                .order_by(MessageAttachment.position)
            ]
            if original_id
            else []
        )
        if ids and ids != original_ids:
            raise _error("CHAT_REGENERATE_INVALID", "重新生成不能替换原问题的附件", 400)
        ids = original_ids
    if not ids:
        return [], []
    records = {
        record.id: record
        for record in db.query(Attachment).filter(
            Attachment.id.in_(ids),
            Attachment.user_id == user_id,
        )
    }
    if len(records) != len(ids):
        raise _error("ATTACHMENT_NOT_FOUND", "附件不存在或不可访问", 404)
    snapshot = [
        {
            "id": key,
            "revision": records[key].revision,
            "accepted_coverage": records[key].accepted_coverage,
        }
        for key in ids
    ]
    return ids, snapshot


def begin_chat_turn(
    db: Session,
    *,
    user_id: int,
    topic_id: int | None,
    session_id: str,
    node_key: str,
    user_input: str,
    mode: str,
    request_id: str,
    model_id: str,
    kind: str = "qa",
    ai_style: str = "标准",
    quote_text: str | None = None,
    quote_source_id: int | None = None,
    regenerate_message_id: int | None = None,
    web_mode: str | None = None,
    attachment_ids: list[str] | None = None,
) -> StartedChatTurn:
    """Claim a session and persist placeholders atomically before streaming starts."""
    topic_id = topic_id or None
    web_mode = web_mode or ("auto" if kind == "qa" else "off")
    if web_mode not in {"auto", "off"} or (kind != "qa" and web_mode != "off"):
        raise ValueError("invalid web mode for chat kind")
    if is_chat_cancelled(db, user_id=user_id, request_id=request_id):
        raise _error("CHAT_REQUEST_CANCELLED", "该请求已停止，请使用新的请求重新发送")
    attachment_ids, attachment_snapshot = _attachment_input(
        db,
        user_id=user_id,
        session_id=session_id,
        mode=mode,
        topic_id=topic_id,
        ids=attachment_ids,
        regenerate_message_id=regenerate_message_id,
    )
    if kind != "qa" and attachment_ids:
        raise _error("ATTACHMENT_SCOPE_MISMATCH", "概览消息不能包含附件", 422)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "session_id": session_id,
                "topic_id": topic_id,
                "node_key": node_key,
                "user_input": user_input,
                "mode": mode,
                "model_id": model_id,
                "kind": kind,
                "ai_style": ai_style,
                "quote_text": quote_text,
                "quote_source_id": quote_source_id,
                "regenerate_message_id": regenerate_message_id,
                "web_mode": web_mode,
                "attachments": attachment_snapshot,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if existing is not None:
        return _replay(db, existing, fingerprint)

    try:
        session = (
            db.query(ChatSession)
            .filter_by(user_id=user_id, session_id=session_id)
            .populate_existing()
            .one_or_none()
        )
        if session is None:
            # Existing local histories remain isolated by their original scope.
            scopes = (
                db.query(ChatMessage.topic_id, ChatMessage.mode)
                .filter_by(user_id=user_id, session_id=session_id, message_type="chat")
                .distinct()
                .all()
            )
            if any(
                (scope.topic_id or None, scope.mode or "socratic") != (topic_id, mode)
                for scope in scopes
            ):
                raise _error("CHAT_SESSION_SCOPE_CONFLICT", "该会话属于其他主题或模式，请新建会话")
            session = ChatSession(
                user_id=user_id,
                session_id=session_id,
                topic_id=topic_id,
                mode=mode,
                summary_model=model_id,
            )
            db.add(session)
            db.flush()
        if (session.topic_id, session.mode) != (topic_id, mode):
            raise _error("CHAT_SESSION_SCOPE_CONFLICT", "该会话属于其他主题或模式，请新建会话")

        now = utcnow()
        token = str(uuid.uuid4())
        previous_request = session.active_request_id
        claimed = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == session.id,
                or_(
                    ChatSession.active_request_id.is_(None),
                    ChatSession.generation_lease_until < now,
                ),
            )
            .update(
                {
                    "active_request_id": request_id,
                    "generation_lease_token": token,
                    "generation_lease_until": now + timedelta(seconds=GENERATION_LEASE_SECONDS),
                },
                synchronize_session=False,
            )
        )
        if not claimed:
            # A simultaneous identical request may have committed between the reads.
            db.rollback()
            existing = get_chat_turn(db, user_id=user_id, request_id=request_id)
            if existing is not None:
                return _replay(db, existing, fingerprint)
            raise _error("CHAT_SESSION_BUSY", "当前会话正在生成回答，请稍后重试")
        if previous_request:
            previous = get_chat_turn(db, user_id=user_id, request_id=previous_request)
            if previous is not None and previous.status == "generating":
                _mark_interrupted(db, previous, "GENERATION_LEASE_EXPIRED")
        db.refresh(session)
        if session.summary_model is None and session.summary_status != "running":
            session.summary_model = model_id
        if is_chat_cancelled(db, user_id=user_id, request_id=request_id):
            raise _error("CHAT_REQUEST_CANCELLED", "该请求已停止，请使用新的请求重新发送")

        if regenerate_message_id is not None:
            user_message = regeneration_question(
                db,
                user_id=user_id,
                session=session,
                answer_id=regenerate_message_id,
                node_key=node_key,
                user_input=user_input,
                kind=kind,
                quote_text=quote_text,
                quote_source_id=quote_source_id,
                attachment_snapshot=attachment_snapshot,
                terminal_statuses=TERMINAL_STATUSES,
            )
        else:
            attachments = (
                validate_for_message(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    topic_id=topic_id,
                    mode=mode,
                    ids=attachment_ids,
                )
                if attachment_ids
                else []
            )
            if attachment_snapshot != [
                {
                    "id": item.id,
                    "revision": item.revision,
                    "accepted_coverage": item.accepted_coverage,
                }
                for item in attachments
            ]:
                raise _error("ATTACHMENT_NOT_READY", "附件状态已更新，请重新发送")
            user_message = ChatMessage(
                user_id=user_id,
                topic_id=topic_id,
                session_id=session_id,
                node_key=node_key[:100],
                role="user",
                content=user_input,
                mode=mode,
                message_type="chat",
                metadata_json={
                    "status": "complete",
                    "request_id": request_id,
                    "kind": kind,
                    "attachment_snapshot": attachment_snapshot,
                    "attachment_derived": bool(attachment_snapshot),
                    **({"quote": quote_text} if quote_text else {}),
                    **({"quote_source_id": quote_source_id} if quote_source_id else {}),
                },
            )
            db.add(user_message)
            db.flush()
            if attachments:
                bind_to_message(
                    db, message_id=user_message.id, session_id=session_id, attachments=attachments
                )
        ai_message = ChatMessage(
            user_id=user_id,
            topic_id=topic_id,
            session_id=session_id,
            node_key=node_key[:100],
            role="ai",
            content="",
            mode=mode,
            message_type="chat",
            metadata_json={
                "status": "streaming",
                "request_id": request_id,
                "user_message_id": user_message.id,
                "kind": kind,
                "node_key": node_key[:100],
                "web": empty_web_snapshot(web_mode, "off" if web_mode == "off" else "deciding"),
                **(
                    {"regenerate_message_id": regenerate_message_id}
                    if regenerate_message_id
                    else {}
                ),
            },
        )
        db.add(ai_message)
        db.flush()
        turn = ChatTurn(
            chat_session_id=session.id,
            user_id=user_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            user_message_id=user_message.id,
            ai_message_id=ai_message.id,
            regenerate_message_id=regenerate_message_id,
            model_id=model_id,
            node_key=node_key[:100],
            kind=kind,
            generation_token=token,
            source_version=session.content_version,
        )
        db.add(turn)
        db.commit()
        return StartedChatTurn(session, turn, user_message, ai_message)
    except IntegrityError:
        db.rollback()
        existing = get_chat_turn(db, user_id=user_id, request_id=request_id)
        if existing is not None:
            return _replay(db, existing, fingerprint)
        raise _error("CHAT_SESSION_BUSY", "当前会话状态已更新，请重试")
    except Exception:
        db.rollback()
        raise


def finish_chat_turn(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    generation_token: str,
    content: str,
    status: str,
    error_code: str | None = None,
    web: dict | None = None,
    usage: dict | None = None,
) -> bool:
    if status not in TERMINAL_STATUSES:
        raise ValueError("invalid chat turn terminal status")
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is None or turn.status != "generating" or turn.generation_token != generation_token:
        return False
    if is_chat_cancelled(db, user_id=user_id, request_id=request_id):
        if status == "complete":
            return False
        status = "interrupted"
        error_code = "USER_CANCELLED"
    values = {
        "active_request_id": None,
        "generation_lease_token": None,
        "generation_lease_until": None,
    }
    if status == "complete" and turn.regenerate_message_id is not None:
        values.update(_invalidate_summary_values())
    owned_session = db.query(ChatSession).filter(
        ChatSession.id == turn.chat_session_id,
        ChatSession.active_request_id == request_id,
        ChatSession.generation_lease_token == turn.generation_token,
        ChatSession.content_version == turn.source_version,
    )
    if status == "complete":
        owned_session = owned_session.filter(ChatSession.generation_lease_until >= utcnow())
    # An expired generation may still release its own lease and persist a failure.
    # The request/token/version checks prevent a late callback touching a new owner.
    changed = owned_session.update(values, synchronize_session=False)
    if not changed:
        db.rollback()
        return False
    message = db.query(ChatMessage).filter_by(id=turn.ai_message_id, user_id=user_id).one_or_none()
    question = (
        db.query(ChatMessage).filter_by(id=turn.user_message_id, user_id=user_id).one_or_none()
    )
    if message is None or question is None:
        db.rollback()
        return False
    message.content = content
    message.metadata_json = {
        **(message.metadata_json or {}),
        **web_metadata(message, content, web=web, status=status, error_code=error_code),
        "status": status,
        **({"error_code": error_code} if error_code else {}),
        **usage_metadata(usage),
    }
    turn.status = status
    turn.error_code = error_code
    turn.finished_at = utcnow()
    if status == "complete" and turn.regenerate_message_id is not None:
        # Replace all prior answers for this question, including failed attempts.
        previous = (
            db.query(ChatTurn)
            .filter(
                ChatTurn.chat_session_id == turn.chat_session_id,
                ChatTurn.user_message_id == turn.user_message_id,
                ChatTurn.id != turn.id,
                ChatTurn.status != "deleted",
            )
            .all()
        )
        previous_ids = {turn.regenerate_message_id}
        for old_turn in previous:
            old_turn.status = "superseded"
            if old_turn.ai_message_id:
                previous_ids.add(old_turn.ai_message_id)
        for old_message in db.query(ChatMessage).filter(
            ChatMessage.id.in_(previous_ids), ChatMessage.user_id == user_id
        ):
            old_message.metadata_json = {
                **(old_message.metadata_json or {}),
                "status": "superseded",
            }
    db.commit()
    return True


def refresh_generation_lease(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    generation_token: str,
    content: str | None = None,
    web: dict | None = None,
    preparation: dict | None = None,
    attachment_derived: bool | None = None,
) -> bool:
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is None or turn.status != "generating" or turn.generation_token != generation_token:
        return False
    if is_chat_cancelled(db, user_id=user_id, request_id=request_id):
        return False
    now = utcnow()
    prepared_state = {**deepcopy(turn.preparation_json or {}), **deepcopy(preparation or {})}
    lease_until = now + timedelta(seconds=GENERATION_LEASE_SECONDS)
    if prepared_state.get("deadline_at"):
        deadline = datetime.fromisoformat(prepared_state["deadline_at"]).replace(
            tzinfo=timezone.utc
        )
        if deadline <= now:
            return False
        lease_until = min(lease_until, deadline)
    claimed = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == turn.chat_session_id,
            ChatSession.active_request_id == request_id,
            ChatSession.generation_lease_token == turn.generation_token,
            ChatSession.content_version == turn.source_version,
            ChatSession.generation_lease_until >= now,
        )
        .update(
            {"generation_lease_until": lease_until},
            synchronize_session=False,
        )
    )
    if not claimed:
        db.rollback()
        return False
    if preparation is not None:
        turn.preparation_json = prepared_state
    if content is not None or web is not None or attachment_derived is not None:
        message = (
            db.query(ChatMessage)
            .filter_by(id=turn.ai_message_id, user_id=user_id)
            .populate_existing()
            .one_or_none()
        )
        if message is None:
            db.rollback()
            return False
        if content is not None:
            message.content = content
        message.metadata_json = {
            **(message.metadata_json or {}),
            **web_metadata(message, message.content, web=web),
            **(
                {"attachment_derived": attachment_derived} if attachment_derived is not None else {}
            ),
        }
    db.commit()
    return True


def cancel_chat_turn(
    db: Session,
    *,
    user_id: int,
    session_id: str,
    request_id: str,
) -> ChatTurn | None:
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is not None:
        owned_session = (
            db.query(ChatSession.id)
            .filter_by(
                id=turn.chat_session_id,
                user_id=user_id,
                session_id=session_id,
            )
            .first()
        )
        if owned_session is None:
            raise _error("CHAT_REQUEST_NOT_FOUND", "请求不属于该会话", 404)
        if turn.status != "generating":
            return turn
    cancellation = (
        db.query(ChatCancellation).filter_by(user_id=user_id, request_id=request_id).one_or_none()
    )
    if cancellation is not None and cancellation.session_id != session_id:
        raise _error("CHAT_REQUEST_CONFLICT", "请求标识已用于其他会话")
    if cancellation is None:
        db.add(ChatCancellation(user_id=user_id, request_id=request_id, session_id=session_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            cancellation = (
                db.query(ChatCancellation)
                .filter_by(user_id=user_id, request_id=request_id)
                .one_or_none()
            )
            if cancellation is None or cancellation.session_id != session_id:
                raise _error("CHAT_REQUEST_CONFLICT", "请求标识已用于其他会话")
    else:
        db.commit()
    # Start a fresh read after publishing the stop intent: begin may have committed
    # while this request was persisting a tombstone for a previously invisible turn.
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is None:
        return None
    session = (
        db.query(ChatSession)
        .filter_by(id=turn.chat_session_id, user_id=user_id, session_id=session_id)
        .one_or_none()
    )
    if session is None:
        return None
    if turn.status != "generating":
        return turn
    changed = (
        db.query(ChatSession)
        .filter_by(
            id=session.id,
            active_request_id=request_id,
            generation_lease_token=turn.generation_token,
        )
        .update(
            {
                "active_request_id": None,
                "generation_lease_token": None,
                "generation_lease_until": None,
            },
            synchronize_session=False,
        )
    )
    if changed:
        _mark_interrupted(db, turn, "USER_CANCELLED")
        db.commit()
    else:
        db.rollback()
    return get_chat_turn(db, user_id=user_id, request_id=request_id)


def invalidate_chat_contexts_for_messages(
    db: Session,
    *,
    user_id: int,
    message_ids: list[int],
    session_id: str | None = None,
    topic_id: int | None = None,
) -> None:
    """Invalidate derived data in the caller's deletion transaction (no commit)."""
    session_names = {
        value
        for (value,) in db.query(ChatMessage.session_id).filter(
            ChatMessage.user_id == user_id,
            ChatMessage.id.in_(message_ids),
        )
    }
    sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id)
    if session_id is not None:
        sessions = sessions.filter(ChatSession.session_id == session_id)
    elif topic_id is not None:
        sessions = sessions.filter(
            or_(ChatSession.topic_id == topic_id, ChatSession.session_id.in_(session_names))
        )
    else:
        sessions = sessions.filter(ChatSession.session_id.in_(session_names))
    ids = [value for (value,) in sessions.with_entities(ChatSession.id)]
    if not ids:
        return
    if session_id is not None or topic_id is not None:
        # Explicitly delete for SQLite deployments without FK enforcement as well.
        db.query(ChatTurn).filter(ChatTurn.chat_session_id.in_(ids)).delete(
            synchronize_session=False
        )
        sessions.delete(synchronize_session=False)
        return
    sessions.update(
        {
            **_invalidate_summary_values(),
            "active_request_id": None,
            "generation_lease_token": None,
            "generation_lease_until": None,
        },
        synchronize_session=False,
    )
    for active in db.query(ChatTurn).filter(
        ChatTurn.chat_session_id.in_(ids), ChatTurn.status == "generating"
    ):
        _mark_interrupted(db, active, "CHAT_CONTEXT_CHANGED")
    for turn in db.query(ChatTurn).filter(
        ChatTurn.chat_session_id.in_(ids),
        or_(ChatTurn.user_message_id.in_(message_ids), ChatTurn.ai_message_id.in_(message_ids)),
    ):
        turn.status = "deleted"
        turn.finished_at = utcnow()
        if turn.user_message_id in message_ids:
            turn.user_message_id = None
        if turn.ai_message_id in message_ids:
            turn.ai_message_id = None
    db.query(ChatTurn).filter(
        ChatTurn.regenerate_message_id.in_(message_ids), ChatTurn.user_id == user_id
    ).update({"regenerate_message_id": None}, synchronize_session=False)
    db.flush()


def checkpoint_interrupted_content(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    generation_token: str,
    content: str,
    usage: dict | None = None,
) -> bool:
    """Persist the last displayed partial after cancellation without reviving a turn."""
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is None or turn.generation_token != generation_token or turn.status != "interrupted":
        return False
    # Lock the context version before rechecking the turn; deletion/regeneration use
    # the same session row, so neither can race between this check and persistence.
    changed = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == turn.chat_session_id,
            ChatSession.content_version == turn.source_version,
        )
        .update({"updated_at": utcnow()}, synchronize_session=False)
    )
    if not changed:
        db.rollback()
        return False
    db.refresh(turn)
    newer_turn = (
        db.query(ChatTurn.id)
        .filter(ChatTurn.chat_session_id == turn.chat_session_id, ChatTurn.id > turn.id)
        .with_for_update()  # MySQL current read, even when the caller already has an older snapshot.
        .first()
    )
    if newer_turn or turn.status != "interrupted" or turn.generation_token != generation_token:
        db.rollback()
        return False
    message = (
        db.query(ChatMessage)
        .filter_by(id=turn.ai_message_id, user_id=user_id)
        .populate_existing()
        .one_or_none()
    )
    report = usage_metadata(usage)
    if (
        message is None
        or not content.startswith(message.content)
        or (
            content == message.content
            and all(
                (message.metadata_json or {}).get(key) == value for key, value in report.items()
            )
        )
    ):
        db.rollback()
        return False
    message.content = content
    message.metadata_json = {
        **(message.metadata_json or {}),
        **web_metadata(message, content, status="interrupted", error_code=turn.error_code),
        **report,
    }
    db.commit()
    return True
