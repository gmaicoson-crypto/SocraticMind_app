"""Exercise new read projections on the deployed dialect, in a disposable database."""

from alembic import command
from sqlalchemy.orm import Session

from models import ChatMessage, ChatSessionTitle, User
from services.chat_history import conversations, session_messages
from test_mysql_baseline import mysql_database as mysql_database


def test_mysql_history_window_and_unicode_projection(mysql_database):
    engine, config, _ = mysql_database
    command.upgrade(config, "head")
    with Session(engine) as db:
        user = User(username="分页测试", email="page@example.test", hashed_password="synthetic")
        other = User(username="隔离测试", email="other@example.test", hashed_password="synthetic")
        db.add_all([user, other])
        db.flush()

        def message(identifier, session="main", owner=None, metadata=None, content="中文🙂" * 100):
            return ChatMessage(
                id=identifier,
                user_id=owner or user.id,
                session_id=session,
                node_key="normal",
                role="ai",
                content=content,
                mode="normal",
                metadata_json=metadata,
            )

        db.add_all(
            [
                message(1),
                message(2, session="older"),
                message(3),
                message(4, metadata={"status": "superseded"}),
                message(5, owner=other.id),
                ChatSessionTitle(
                    user_id=user.id,
                    session_id="main",
                    mode="normal",
                    title="可见标题",
                    status="manual",
                ),
                ChatSessionTitle(
                    user_id=other.id,
                    session_id="older",
                    mode="normal",
                    title="不可见",
                    status="manual",
                ),
            ]
        )
        db.commit()
        first = conversations(db, user_id=user.id, mode="normal", limit=1)
        assert first["snapshot_id"] == 3
        assert first["next_before_id"] == 3
        assert first["items"][0]["title"] == "可见标题"
        assert len(first["items"][0]["preview"]) == 160
        db.add(message(6, session="older"))
        db.commit()
        older = conversations(
            db, user_id=user.id, mode="normal", limit=1, snapshot_id=3, before_id=3
        )
        assert older["items"][0]["last_message_id"] == 2
        assert older["items"][0]["title"] is None
        assert older["next_before_id"] is None
        history = session_messages(db, user_id=user.id, session_id="main", limit=1)
        assert [item["id"] for item in history["items"]] == [3]
        assert history["next_before_id"] == 3
        tail = session_messages(
            db, user_id=user.id, session_id="main", limit=1, snapshot_id=3, before_id=3
        )
        assert [item["id"] for item in tail["items"]] == [1]
        assert tail["next_before_id"] is None
