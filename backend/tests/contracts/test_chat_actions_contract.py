"""Provider contracts for mobile title and deletion actions, with isolated synthetic histories."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from core.deps import get_current_user
from models import ChatMessage, ChatSessionTitle, User
from services.chat_lifecycle import begin_chat_turn, finish_chat_turn
from services.chat_titles import run_one_title_job


DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/chat-actions.json").read_text()
)
SID = DATA["session_id"]


def seed(db, user, identifier=101, session_id=SID):
    row = ChatMessage(
        id=identifier,
        user_id=user.id,
        session_id=session_id,
        mode="normal",
        node_key="__normal__",
        role="user",
        content="合成问题",
        message_type="chat",
    )
    db.add(row)
    db.commit()
    return row


def test_json_rename_supports_opaque_id_without_model_or_existing_title(
    client, db_session, auth_user, monkeypatch
):
    seed(db_session, auth_user)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Manual rename must not resolve or call a model")

    monkeypatch.setattr("routers.chat_titles.resolve_model_id", forbidden)
    renamed = client.put("/api/chat/session-titles", json=DATA["rename"])
    assert renamed.status_code == 200
    assert renamed.json() == DATA["renamed"]
    assert client.get("/api/chat/session-titles", params={"ids": SID}).json() == DATA["titles"]
    assert client.put("/api/chat/session-titles", json=DATA["rename"]).json() == DATA["renamed"]
    row = db_session.query(ChatSessionTitle).one()
    assert row.source_text is None and row.lease_token is None and row.next_retry_at is None
    assert not run_one_title_job(lambda: Session(bind=db_session.get_bind()))
    summary = client.get("/api/chat/sessions", params={"mode": "normal"}).json()["items"][0]
    assert summary["title"] == DATA["renamed"]["title"] and summary["title_status"] == "manual"


@pytest.mark.parametrize("title", [" ", "字" * 41])
def test_rename_validates_normalized_title_and_missing_session(
    client, db_session, auth_user, title
):
    seed(db_session, auth_user)
    assert (
        client.put("/api/chat/session-titles", json={"session_id": SID, "title": title}).status_code
        == 422
    )
    assert (
        client.put(
            "/api/chat/session-titles", json={"session_id": " ", "title": "有效"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/chat/session-titles", json={"session_id": "missing", "title": "有效"}
        ).status_code
        == 404
    )
    emoji = "🙂" * 40
    assert (
        client.put("/api/chat/session-titles", json={"session_id": SID, "title": emoji}).json()[
            "title"
        ]
        == emoji
    )


def test_rename_and_delete_are_scoped_to_authenticated_owner(client, app, db_session, auth_user):
    seed(db_session, auth_user)
    seed(db_session, auth_user, 102)
    other = User(
        username="actions-other", email="actions-other@example.test", hashed_password="test"
    )
    db_session.add(other)
    db_session.commit()
    seed(db_session, other, 103)
    assert client.put("/api/chat/session-titles", json=DATA["rename"]).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.get("/api/chat/session-titles", params={"ids": SID}).json() == []
    result = client.request("DELETE", "/api/chat/messages", json={"ids": [101, 103]})
    assert result.json() == {"deleted": 1}
    assert db_session.query(ChatMessage).filter_by(user_id=auth_user.id).count() == 2
    assert client.put("/api/chat/session-titles", json=DATA["rename"]).status_code == 404
    assert client.request("DELETE", "/api/chat/session", json={"session_id": SID}).json() == {
        "deleted": 0
    }
    app.dependency_overrides[get_current_user] = lambda: auth_user
    assert client.get("/api/chat/session-titles", params={"ids": SID}).json() == DATA["titles"]


def test_delete_messages_matches_shared_body_and_count(client, db_session, auth_user):
    for identifier in DATA["message_ids"]:
        seed(db_session, auth_user, identifier)
    assert (
        client.request("DELETE", "/api/chat/messages", json={"ids": DATA["message_ids"]}).json()
        == DATA["deleted_messages"]
    )
    assert client.request(
        "DELETE", "/api/chat/messages", json={"ids": DATA["message_ids"]}
    ).json() == {"deleted": 0}


def test_delete_session_invalidates_writer_removes_title_and_is_idempotent(
    client, db_session, auth_user
):
    started = begin_chat_turn(
        db_session,
        user_id=auth_user.id,
        topic_id=None,
        session_id=SID,
        node_key="__normal__",
        user_input="合成问题",
        mode="normal",
        request_id="active",
        model_id="fake-model",
    )
    assert client.put("/api/chat/session-titles", json=DATA["rename"]).status_code == 200
    response = client.request("DELETE", "/api/chat/session", json={"session_id": SID})
    assert response.json() == DATA["deleted_session"]
    assert client.get("/api/chat/session-titles", params={"ids": SID}).json() == []
    assert (
        client.get("/api/chat/session-messages", params={"session_id": SID}).json()["items"] == []
    )
    missing = client.get("/api/chat/requests/active")
    assert missing.status_code == 404  # Whole-session deletion removes the request ledger too.
    assert missing.json()["code"] == "CHAT_REQUEST_NOT_FOUND"
    assert client.post(
        "/api/chat/cancel", json={"session_id": SID, "request_id": "active"}
    ).json() == {"status": "interrupted"}
    assert not finish_chat_turn(
        db_session,
        user_id=auth_user.id,
        request_id="active",
        generation_token=started.turn.generation_token,
        content="迟到",
        status="complete",
    )
    assert client.request("DELETE", "/api/chat/session", json={"session_id": SID}).json() == {
        "deleted": 0
    }


def test_json_rename_invalidates_inflight_title_worker_and_legacy_route_stays_compatible(
    client, db_session, auth_user
):
    seed(db_session, auth_user, session_id="legacy")
    client.post(
        "/api/chat/session-titles",
        json={"session_id": "legacy", "mode": "normal", "message": "问题"},
    )

    def generate(schema, *_args, **_kwargs):
        assert (
            client.put(
                "/api/chat/session-titles", json={"session_id": "legacy", "title": "手动标题"}
            ).status_code
            == 200
        )
        return SimpleNamespace(value=schema(title="迟到标题"))

    assert run_one_title_job(
        lambda: Session(bind=db_session.get_bind(), expire_on_commit=False), generator=generate
    )
    assert (
        client.get("/api/chat/session-titles", params={"ids": "legacy"}).json()[0]["title"]
        == "手动标题"
    )
    assert (
        client.put("/api/chat/session-titles/legacy", json={"title": "旧客户端"}).json()["title"]
        == "旧客户端"
    )


def test_bulk_titles_preserve_opaque_ids_return_subset_and_scope_owner(
    client, app, db_session, auth_user
):
    for item in DATA["batch_titles"]:
        db_session.add(
            ChatSessionTitle(
                user_id=auth_user.id,
                session_id=item["session_id"],
                mode="normal",
                title=item["title"],
                status=item["status"],
                next_retry_at=datetime(2026, 10, 24) if item["retry_pending"] else None,
            )
        )
    other = User(username="titles-other", email="titles-other@example.test", hashed_password="test")
    db_session.add(other)
    db_session.commit()
    db_session.add(
        ChatSessionTitle(
            user_id=other.id,
            session_id=DATA["batch_ids"][2],
            mode="normal",
            title="其他账号",
            status="manual",
        )
    )
    db_session.commit()
    response = client.get(
        "/api/chat/session-titles", params=[("ids", x) for x in DATA["batch_ids"]]
    )
    assert response.status_code == 200
    assert sorted(response.json(), key=lambda x: x["session_id"]) == sorted(
        DATA["batch_titles"], key=lambda x: x["session_id"]
    )
    assert (
        client.get(
            "/api/chat/session-titles", params=[("ids", f"s{x}") for x in range(101)]
        ).status_code
        == 422
    )
    app.dependency_overrides[get_current_user] = lambda: other
    response = client.get(
        "/api/chat/session-titles", params=[("ids", x) for x in DATA["batch_ids"]]
    )
    assert [row["session_id"] for row in response.json()] == [DATA["batch_ids"][2]]
