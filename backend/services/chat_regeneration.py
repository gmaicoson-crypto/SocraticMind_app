"""Resolve the original question inside the lifecycle owner's existing transaction."""

from core.errors import ApiError
from models import ChatMessage, ChatTurn


def _invalid(message="该回答无法重新生成"):
    return ApiError(
        status_code=400, code="CHAT_REGENERATE_INVALID", message=message, retryable=False
    )


def regeneration_question(
    db,
    *,
    user_id,
    session,
    answer_id,
    node_key,
    user_input,
    kind,
    quote_text,
    quote_source_id,
    attachment_snapshot,
    terminal_statuses,
):
    """Check stored context without committing, changing the question or selecting a new model."""
    old_turn = (
        db.query(ChatTurn)
        .filter_by(user_id=user_id, chat_session_id=session.id, ai_message_id=answer_id)
        .one_or_none()
    )
    answer = (
        db.query(ChatMessage)
        .filter_by(
            id=answer_id,
            user_id=user_id,
            session_id=session.session_id,
            role="ai",
            message_type="chat",
        )
        .one_or_none()
    )
    if (
        answer is None
        or (answer.metadata_json or {}).get("status", "complete") not in terminal_statuses
    ):
        raise _invalid()
    if old_turn is not None:
        if old_turn.status not in terminal_statuses:
            raise _invalid()
        question = (
            db.get(ChatMessage, old_turn.user_message_id) if old_turn.user_message_id else None
        )
        if old_turn.kind != kind or old_turn.node_key != node_key[:100]:
            raise _invalid("重新生成需要使用原问题的节点和类型")
    else:
        question = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session.session_id,
                ChatMessage.role == "user",
                ChatMessage.message_type == "chat",
                ChatMessage.id < answer.id,
            )
            .order_by(ChatMessage.id.desc())
            .first()
        )
    if (
        question is None
        or question.role != "user"
        or question.message_type != "chat"
        or question.content != user_input
    ):
        raise _invalid("重新生成需要对应原问题")
    for message in (question, answer):
        if (
            message.user_id != user_id
            or message.session_id != session.session_id
            or message.mode != session.mode
            or message.topic_id != session.topic_id
            or message.node_key != node_key[:100]
            or (message.metadata_json or {}).get("kind", "qa") != kind
        ):
            raise _invalid("重新生成需要使用原问题的节点和类型")
    metadata = question.metadata_json or {}
    if (quote_text or None) != (metadata.get("quote") or None) or quote_source_id != metadata.get(
        "quote_source_id"
    ):
        raise _invalid("重新生成不能替换或省略原问题的引用")
    if attachment_snapshot != metadata.get("attachment_snapshot", []):
        raise _invalid("原问题附件已改变或不可用")
    if (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.user_id == user_id,
            ChatMessage.session_id == session.session_id,
            ChatMessage.role == "user",
            ChatMessage.message_type == "chat",
            ChatMessage.id > question.id,
        )
        .first()
        is not None
    ):
        raise ApiError(
            status_code=400,
            code="CHAT_REGENERATE_NOT_LATEST",
            message="仅支持重新生成当前会话最后一轮回答",
            retryable=False,
        )
    return question
