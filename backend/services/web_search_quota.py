"""Atomic, conservative query reservations shared by API processes.

A reservation is retained on timeout/cancel: the provider may already have
charged. The ledger is deliberately independent of chat-history deletion.
"""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import settings
from models import ChatMessage, WebSearchQuota
from services.chat_lifecycle import get_chat_turn, refresh_generation_lease


def reserve_web_queries(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    generation_token: str,
    queries: int,
) -> bool:
    if not 1 <= queries <= 2:
        raise ValueError("one search batch must reserve one or two queries")
    if not refresh_generation_lease(
        db, user_id=user_id, request_id=request_id, generation_token=generation_token
    ):
        db.rollback()
        return False
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    message = db.get(ChatMessage, turn.ai_message_id) if turn else None
    if message is None:
        db.rollback()
        return False
    existing = (message.metadata_json or {}).get("web_query_reservation")
    if existing:
        db.rollback()
        return existing.get("queries") == queries
    # A new transaction follows the lease check. Quota updates lock in a fixed
    # global-then-user order, avoiding lost increments across concurrent sessions.
    day = datetime.now(timezone.utc).date()
    for scope, limit in (
        ("tavily", settings.web_search_global_daily_query_limit),
        (f"user:{user_id}", settings.web_search_daily_query_limit),
    ):
        try:
            with db.begin_nested():
                db.add(WebSearchQuota(scope=scope, day=day, used_queries=0))
                db.flush()
        except IntegrityError:
            pass
        claimed = (
            db.query(WebSearchQuota)
            .filter(
                WebSearchQuota.scope == scope,
                WebSearchQuota.day == day,
                WebSearchQuota.used_queries + queries <= limit,
            )
            .update(
                {"used_queries": WebSearchQuota.used_queries + queries},
                synchronize_session=False,
            )
        )
        if not claimed:
            db.rollback()
            return False
    turn = get_chat_turn(db, user_id=user_id, request_id=request_id)
    if turn is None:
        db.rollback()
        return False
    message = db.get(ChatMessage, turn.ai_message_id)
    if message is None:
        db.rollback()
        return False
    existing = (message.metadata_json or {}).get("web_query_reservation")
    if existing:
        db.rollback()
        return existing.get("queries") == queries
    message.metadata_json = {
        **(message.metadata_json or {}),
        "web_query_reservation": {"queries": queries, "day": day.isoformat()},
    }
    # This guarded lease update commits the reservation and the message marker
    # together, or rolls both back if cancellation/deletion won the race.
    if not refresh_generation_lease(
        db, user_id=user_id, request_id=request_id, generation_token=generation_token
    ):
        db.rollback()
        return False
    return True
