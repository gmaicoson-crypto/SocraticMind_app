"""Usage metadata and stopped-writer fencing on the actual MySQL dialect."""

from alembic import command
from sqlalchemy.orm import Session

from models import ChatMessage, User
from services.chat_history import turn_usage
from services.chat_lifecycle import (
    cancel_chat_turn,
    checkpoint_interrupted_content,
    refresh_generation_lease,
)
from test_mysql_baseline import mysql_database as mysql_database
from tests.feedback_cases import DATA
from tests.p0.test_chat_lifecycle import start


def test_mysql_usage_checkpoint_and_new_turn_fence(mysql_database):
    engine, config, _ = mysql_database
    command.upgrade(config, "head")
    with Session(engine) as db:
        user = User(username="用量测试", email="usage@example.test", hashed_password="synthetic")
        db.add(user)
        db.commit()
        attempt = start(db, user.id)
        arguments = dict(
            user_id=user.id,
            request_id=attempt.turn.request_id,
            generation_token=attempt.turn.generation_token,
            content="已停止的回答🙂",
        )
        assert refresh_generation_lease(db, **arguments)
        cancel_chat_turn(
            db, user_id=user.id, session_id="conversation", request_id=attempt.turn.request_id
        )
        assert checkpoint_interrupted_content(db, **arguments, usage=DATA["reported_usage"])
        assert turn_usage(db, attempt.turn) == DATA["reported_usage"]
        answer_id = attempt.ai_message.id
        db.rollback()
        with Session(engine) as another_connection:
            newer = start(another_connection, user.id, "new-request")
            newer_id = newer.ai_message.id
        assert not checkpoint_interrupted_content(db, **arguments, usage=DATA["zero_usage"])
        db.expire_all()
        assert db.get(ChatMessage, answer_id).metadata_json["usage"] == DATA["reported_usage"]
        assert "usage" not in db.get(ChatMessage, newer_id).metadata_json
