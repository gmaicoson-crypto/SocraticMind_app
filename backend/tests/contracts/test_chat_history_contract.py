"""Provider evidence for the same bounded pages consumed by both native cores."""

from datetime import datetime
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event

from core.database import get_db
from models import ChatMessage, ChatSessionTitle, User
from routers.chat_history import router
from services.chat_lifecycle import begin_chat_turn, finish_chat_turn


DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/chat-history.json").read_text()
)
SID = DATA["session_id"]


def add_message(db, user_id, identifier, session_id=SID, **fields):
    values = dict(
        id=identifier,
        user_id=user_id,
        session_id=session_id,
        node_key="normal",
        mode="normal",
        role="ai",
        content="更早回答",
        message_type="chat",
        created_at=datetime(2026, 10, 23, 8, 10),
    )
    values.update(fields)
    row = ChatMessage(**values)
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def history(db_session, auth_user):
    for page in ("messages_first", "messages_older"):
        for item in DATA[page]["items"]:
            fields = {key: item[key] for key in ("role", "content", "mode", "node_key")}
            add_message(
                db_session, auth_user.id, item["id"], metadata_json=item["metadata"], **fields
            )
    add_message(db_session, auth_user.id, 99, session_id="older-session")
    db_session.add(
        ChatSessionTitle(
            user_id=auth_user.id,
            session_id=SID,
            mode="normal",
            title="合成测试对话",
            status="manual",
        )
    )
    db_session.commit()


def test_messages_and_summaries_match_native_fixture(client, history):
    first = client.get("/api/chat/session-messages", params={"session_id": SID, "limit": 2})
    assert first.status_code == 200
    assert first.json() == DATA["messages_first"]
    older = client.get(
        "/api/chat/session-messages",
        params={"session_id": SID, "limit": 2, "snapshot_id": 104, "before_id": 103},
    )
    assert older.json() == DATA["messages_older"]
    summaries = client.get("/api/chat/sessions", params={"mode": "normal", "limit": 1})
    assert summaries.json() == DATA["sessions_first"]
    older_summaries = client.get(
        "/api/chat/sessions", params={"limit": 1, "snapshot_id": 104, "before_id": 104}
    )
    assert older_summaries.json() == DATA["sessions_older"]


def test_insert_and_delete_between_pages_do_not_shift_older_messages(
    client, history, db_session, auth_user
):
    add_message(db_session, auth_user.id, 105, content="翻页后的新回答")
    db_session.query(ChatMessage).filter_by(id=103).delete()
    db_session.commit()
    older = client.get(
        "/api/chat/session-messages",
        params={"session_id": SID, "limit": 2, "snapshot_id": 104, "before_id": 103},
    )
    assert older.json() == DATA["messages_older"]
    assert (
        client.get("/api/chat/session-messages", params={"session_id": SID}).json()["items"][0][
            "id"
        ]
        == 105
    )


def test_new_activity_does_not_move_unread_conversation_out_of_fixed_page(
    client, history, db_session, auth_user
):
    add_message(db_session, auth_user.id, 106, session_id="older-session", content="新的活动")
    add_message(db_session, auth_user.id, 107, session_id="new-session")
    page = client.get(
        "/api/chat/sessions", params={"limit": 1, "snapshot_id": 104, "before_id": 104}
    )
    assert page.json() == DATA["sessions_older"]
    refreshed = client.get("/api/chat/sessions").json()
    assert [item["last_message_id"] for item in refreshed["items"]] == [107, 106, 104]


def test_modes_and_accounts_never_mix_even_with_same_session_id(
    client, history, db_session, auth_user
):
    other = User(username="other", email="other@example.test", hashed_password="synthetic")
    db_session.add(other)
    db_session.commit()
    add_message(db_session, other.id, 200, content="另一账号的内容")
    add_message(db_session, other.id, 201, session_id="foreign-only")
    db_session.add(
        ChatSessionTitle(
            user_id=other.id,
            session_id="older-session",
            mode="normal",
            title="不能泄露",
            status="manual",
        )
    )
    add_message(
        db_session, auth_user.id, 202, session_id="learning", mode="socratic", node_key="node-a"
    )
    assert client.get("/api/chat/sessions", params={"limit": 1}).json() == DATA["sessions_first"]
    assert (
        client.get("/api/chat/sessions", params={"mode": "socratic"}).json()["items"][0][
            "session_id"
        ]
        == "learning"
    )
    own = client.get("/api/chat/session-messages", params={"session_id": SID}).json()
    assert [item["id"] for item in own["items"]] == [104, 103, 102, 101]
    for session_id in ("foreign-only", "unknown"):
        assert (
            client.get("/api/chat/session-messages", params={"session_id": session_id}).json()
            == DATA["empty"]
        )
    summary = client.get("/api/chat/sessions", params={"snapshot_id": 104, "before_id": 104}).json()
    assert summary["items"][0]["title"] is None


def test_visible_regeneration_and_legacy_routes_share_one_projection(client, db_session, auth_user):
    def start(request_id, **extra):
        return begin_chat_turn(
            db_session,
            user_id=auth_user.id,
            topic_id=None,
            session_id="regenerate",
            node_key="normal",
            user_input="问题",
            mode="normal",
            request_id=request_id,
            model_id="test-model",
            **extra,
        )

    def finish(started, status, content):
        assert finish_chat_turn(
            db_session,
            user_id=auth_user.id,
            request_id=started.turn.request_id,
            content=content,
            status=status,
            generation_token=started.turn.generation_token,
        )

    first = start("original")
    finish(first, "complete", "原回答")
    failed = start("failed", regenerate_message_id=first.ai_message.id)
    finish(failed, "failed", "不可见重试")
    successful = start("successful", regenerate_message_id=first.ai_message.id)
    finish(successful, "complete", "替换回答")
    expected = [successful.ai_message.id, first.user_message.id]
    page = client.get("/api/chat/session-messages", params={"session_id": "regenerate"}).json()
    assert [item["id"] for item in page["items"]] == expected
    assert client.get("/api/chat/messages").json() == page["items"]
    assert client.get("/api/chat/history/normal").json() == list(reversed(page["items"]))
    assert client.get("/api/chat/sessions").json()["items"][0]["preview"] == "替换回答"


def test_session_history_reaches_beyond_fifty_and_preserves_legacy_order(
    client, db_session, auth_user
):
    for identifier in range(1, 66):
        add_message(db_session, auth_user.id, identifier, content=f"消息 {identifier}")
    ids, cursor = [], {}
    while True:
        response = client.get(
            "/api/chat/session-messages", params={"session_id": SID, "limit": 20, **cursor}
        )
        assert response.status_code == 200
        page = response.json()
        ids.extend(item["id"] for item in page["items"])
        if page["next_before_id"] is None:
            break
        cursor = {"snapshot_id": page["snapshot_id"], "before_id": page["next_before_id"]}
    assert ids == list(range(65, 0, -1))
    assert [item["id"] for item in client.get("/api/chat/history/normal").json()] == list(
        range(1, 51)
    )


def test_summaries_are_bounded_and_do_not_load_full_message_body(client, db_session, auth_user):
    add_message(db_session, auth_user.id, 1, content="中文🙂" * 5000)
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = client.get("/api/chat/sessions").json()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(page["items"][0]["preview"]) == 160
    assert len(statements) == 2
    assert "substr(chat_messages.content" in statements[1]
    assert "chat_messages.metadata_json AS" not in statements[1]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"before_id": 0},
        {"snapshot_id": -1},
        {"before_id": 2},
        {"before_id": 3, "snapshot_id": 2},
        {"mode": "unknown"},
    ],
)
def test_invalid_session_page_inputs_are_rejected(client, params):
    assert client.get("/api/chat/sessions", params=params).status_code == 422


@pytest.mark.parametrize("session_id", ["", "   ", "x" * 101])
def test_invalid_message_session_is_rejected(client, session_id):
    assert (
        client.get("/api/chat/session-messages", params={"session_id": session_id}).status_code
        == 422
    )


def test_authentication_is_required_on_both_new_routes(db_session):
    app = FastAPI()
    app.include_router(router, prefix="/api/chat")
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        assert client.get("/api/chat/sessions").status_code == 401
        assert (
            client.get("/api/chat/session-messages", params={"session_id": SID}).status_code == 401
        )
