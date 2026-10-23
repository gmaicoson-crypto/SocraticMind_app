"""Visible-history projection; generation state and transactions stay in chat_lifecycle."""

from copy import deepcopy

from sqlalchemy import and_, exists, func

from models import ChatMessage, ChatSessionTitle, ChatTurn
from services.attachments.evidence import hydrate_message_sources
from services.attachments.service import summaries_for_messages


def history_responses(db, messages):
    attachments = summaries_for_messages(db, [message.id for message in messages])
    sources = (
        hydrate_message_sources(db, user_id=messages[0].user_id, messages=messages)
        if messages
        else {}
    )

    def metadata(message):
        result = deepcopy(message.metadata_json)
        if result and result.get("web") is not None and message.id in sources:
            result["web"]["sources"] = sources[message.id]
        return result

    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "node_key": message.node_key,
            "mode": message.mode,
            "topic_id": message.topic_id,
            "session_id": message.session_id,
            "message_type": message.message_type,
            "metadata": metadata(message),
            "created_at": message.created_at,
            "attachments": attachments.get(message.id, []),
        }
        for message in messages
    ]


def visible_messages(query):
    hidden_retry = exists().where(
        ChatTurn.ai_message_id == ChatMessage.id,
        ChatTurn.regenerate_message_id.is_not(None),
        ChatTurn.status.in_(["failed", "interrupted"]),
    )
    return query.filter(
        func.coalesce(ChatMessage.metadata_json["status"].as_string(), "complete") != "superseded",
        ~hidden_retry,
    )


def session_messages(db, *, user_id, session_id, limit, before_id=None, snapshot_id=None):
    query = visible_messages(db.query(ChatMessage)).filter(
        ChatMessage.user_id == user_id, ChatMessage.session_id == session_id
    )
    if snapshot_id is None:
        snapshot_id = query.with_entities(func.max(ChatMessage.id)).scalar() or 0
    query = query.filter(ChatMessage.id <= snapshot_id)
    if before_id is not None:
        query = query.filter(ChatMessage.id < before_id)
    rows = query.order_by(ChatMessage.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    return {
        "items": history_responses(db, page),
        "snapshot_id": snapshot_id,
        "next_before_id": page[-1].id if len(rows) > limit else None,
    }


def conversations(db, *, user_id, mode, limit, before_id=None, snapshot_id=None):
    # Derive from visible messages so legacy / agent sessions without ChatSession still appear.
    visible = visible_messages(db.query(ChatMessage)).filter(
        ChatMessage.user_id == user_id, ChatMessage.mode == mode
    )
    if snapshot_id is None:
        snapshot_id = visible.with_entities(func.max(ChatMessage.id)).scalar() or 0
    latest = (
        visible.filter(ChatMessage.id <= snapshot_id)
        .with_entities(func.max(ChatMessage.id).label("last_id"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    query = (
        db.query(
            ChatMessage.session_id,
            ChatMessage.mode,
            ChatMessage.topic_id,
            ChatMessage.node_key,
            ChatMessage.id.label("last_message_id"),
            ChatMessage.role.label("last_role"),
            func.substr(ChatMessage.content, 1, 160).label("preview"),
            ChatMessage.created_at.label("updated_at"),
            ChatSessionTitle.title,
            ChatSessionTitle.status.label("title_status"),
        )
        .join(latest, latest.c.last_id == ChatMessage.id)
        .outerjoin(
            ChatSessionTitle,
            and_(
                ChatSessionTitle.user_id == user_id,
                ChatSessionTitle.session_id == ChatMessage.session_id,
                ChatSessionTitle.mode == ChatMessage.mode,
            ),
        )
    )
    if before_id is not None:
        query = query.filter(ChatMessage.id < before_id)
    rows = query.order_by(ChatMessage.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    return {
        "items": [dict(row._mapping) for row in page],
        "snapshot_id": snapshot_id,
        "next_before_id": page[-1].last_message_id if len(rows) > limit else None,
    }
