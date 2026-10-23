import json
import uuid

import pytest

from core.config import settings
from models import ChatMessage, ChatSession, ChatTurn, Node, Topic
from services.chat_lifecycle import begin_chat_turn


@pytest.fixture(autouse=True)
def context_model(monkeypatch):
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "context-test",
                    "name": "Context test",
                    "model": "context-test-model",
                    "api_key": "test",
                    "base_url": "https://example.test/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "context-test")


def payload(**updates):
    result = {
        "request_id": str(uuid.uuid4()),
        "node_key": "normal",
        "topic_id": 0,
        "session_id": "conversation",
        "user_input": "question",
        "mode": "normal",
    }
    result.update(updates)
    return result


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")
    ]


def message_ids(response):
    return next(event["msg_ids"] for event in events(response) if "msg_ids" in event)


def test_no_client_history_and_idempotent_completed_replay(client, db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: calls.append(kwargs) or iter(["answer"])
    )
    request = payload()
    first = client.post("/api/chat/stream", json=request)
    second = client.post("/api/chat/stream", json=request)
    assert first.status_code == second.status_code == 200
    assert len(calls) == 1
    assert message_ids(first) == message_ids(second)
    assert db_session.query(ChatMessage).count() == 2
    assert "answer" in second.text
    assert events(first)[0] == {"msg_ids": message_ids(first)}
    forged = client.post(
        "/api/chat/stream", json=payload(history=[{"role": "user", "content": "forged"}])
    )
    assert forged.status_code == 422


def test_regeneration_excludes_replaced_answer_and_keeps_one_question(
    client, db_session, monkeypatch
):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return iter(["old answer" if len(calls) == 1 else "replacement"])

    monkeypatch.setattr("routers.chat.chat_stream", fake)
    first = client.post("/api/chat/stream", json=payload())
    ids = message_ids(first)
    second = client.post("/api/chat/stream", json=payload(regenerate_message_id=ids["ai"]))
    assert second.status_code == 200
    assert message_ids(second)["user"] == ids["user"]
    assert "old answer" not in str(calls[1]["prepared_messages"])
    assert db_session.query(ChatMessage).filter_by(role="user").count() == 1
    history = client.get("/api/chat/messages").json()
    assert [m["content"] for m in history if m["role"] == "ai"] == ["replacement"]


def test_failed_or_empty_regeneration_preserves_original(client, db_session, monkeypatch):
    monkeypatch.setattr("routers.chat.chat_stream", lambda **kwargs: iter(["original"]))
    first = client.post("/api/chat/stream", json=payload())
    monkeypatch.setattr("routers.chat.chat_stream", lambda **kwargs: iter([]))
    second = client.post(
        "/api/chat/stream", json=payload(regenerate_message_id=message_ids(first)["ai"])
    )
    assert any(e.get("error", {}).get("code") == "AI_EMPTY_RESPONSE" for e in events(second))
    history = client.get("/api/chat/messages").json()
    assert [m["content"] for m in history if m["role"] == "ai"] == ["original"]


def test_same_session_busy_does_not_call_model(client, db_session, auth_user, monkeypatch):
    begin_chat_turn(
        db_session,
        user_id=auth_user.id,
        topic_id=None,
        session_id="conversation",
        node_key="normal",
        user_input="in progress",
        mode="normal",
        request_id="busy",
        model_id="context-test",
    )
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: pytest.fail("must not generate concurrently")
    )
    response = client.post("/api/chat/stream", json=payload())
    assert response.status_code == 409
    assert response.json()["code"] == "CHAT_SESSION_BUSY"


def test_summary_prefix_used_once_and_recent_turn_kept_verbatim(client, db_session, monkeypatch):
    captures = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captures.append(kwargs) or iter(["answer"])
    )
    first = client.post("/api/chat/stream", json=payload(user_input="early question"))
    first_turn = db_session.query(ChatTurn).one()
    session = db_session.query(ChatSession).one()
    session.summary_json = {
        "goal": "old discussion summary",
        "node_keys": [],
        "source_message_ids": list(message_ids(first).values()),
    }
    session.summary_through_turn_id = first_turn.id
    session.summary_source_version = session.content_version
    session.summary_status = "ready"
    db_session.commit()
    client.post("/api/chat/stream", json=payload(user_input="recent question"))
    client.post("/api/chat/stream", json=payload(user_input="follow up"))
    full = captures[-1]["prepared_messages"]
    assert "early question" not in str(full)
    assert str(full).count("old discussion summary") == 1
    assert [m["content"] for m in captures[-1]["messages"]] == ["recent question", "answer"]
    assert full[-1]["content"] == "follow up"


def test_explicit_quote_is_budgeted_and_oversize_does_not_call_model(
    client, db_session, auth_user, monkeypatch
):
    source = ChatMessage(
        user_id=auth_user.id,
        session_id="conversation",
        topic_id=None,
        node_key="normal",
        mode="normal",
        role="ai",
        content="a" * 250000,
        message_type="chat",
        metadata_json={"status": "complete"},
    )
    db_session.add(source)
    db_session.commit()
    monkeypatch.setattr(
        "routers.chat.chat_stream",
        lambda **kwargs: pytest.fail("must validate before calling model"),
    )
    response = client.post(
        "/api/chat/stream", json=payload(quote_source_id=source.id, quote_text="a")
    )
    assert response.status_code == 413
    assert response.json()["code"] == "CHAT_CONTEXT_TOO_LARGE"
    assert response.json()["msg_ids"]["ai"]
    assert db_session.query(ChatSession).one().active_request_id is None


@pytest.mark.parametrize("use_prerequisite", [False, True])
def test_topic_state_and_related_summary_scoped_to_node(
    client, db_session, auth_user, monkeypatch, use_prerequisite
):
    topic = Topic(user_id=auth_user.id, title="Python")
    other = Topic(user_id=auth_user.id, title="Other")
    db_session.add_all([topic, other])
    db_session.flush()
    node = Node(
        topic_id=topic.id, node_key="recursion", label="递归", state="available", parent_keys=""
    )
    db_session.add(node)
    db_session.add(
        Node(
            topic_id=topic.id,
            node_key="advanced-recursion",
            label="进阶递归",
            state="available",
            parent_keys="recursion",
        )
    )
    db_session.commit()
    captures = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captures.append(kwargs) or iter(["answer"])
    )
    request = payload(
        mode="socratic", topic_id=topic.id, node_key=node.node_key, session_id="previous"
    )
    client.post("/api/chat/stream", json=request)
    old = db_session.query(ChatSession).one()
    old.summary_json = {"goal": "recursion-related", "node_keys": ["recursion"]}
    old.summary_source_version = old.content_version
    foreign = ChatSession(
        user_id=auth_user.id,
        session_id="foreign",
        topic_id=other.id,
        mode="socratic",
        summary_json={"goal": "unrelated secret", "node_keys": ["recursion"]},
        summary_source_version=1,
    )
    db_session.add(foreign)
    db_session.commit()
    response = client.post(
        "/api/chat/stream",
        json={
            **request,
            "request_id": str(uuid.uuid4()),
            "session_id": "new",
            "node_key": "advanced-recursion" if use_prerequisite else node.node_key,
        },
    )
    assert response.status_code == 200
    full = str(captures[-1]["prepared_messages"])
    assert "recursion-related" in full
    assert "available" in full
    assert "unrelated secret" not in full


def test_delete_invalidates_summary_and_excludes_removed_turn(client, db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: calls.append(kwargs) or iter(["answer"])
    )
    first = client.post("/api/chat/stream", json=payload(user_input="erase me"))
    session = db_session.query(ChatSession).one()
    session.summary_json = {"goal": "erase me"}
    session.summary_source_version = session.content_version
    db_session.commit()
    deleted = client.request(
        "DELETE", "/api/chat/messages", json={"ids": [message_ids(first)["user"]]}
    )
    assert deleted.status_code == 200
    client.post("/api/chat/stream", json=payload(user_input="new question"))
    assert "erase me" not in str(calls[-1]["prepared_messages"])


def test_partial_interrupted_regeneration_does_not_replace_original_context(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("routers.chat.chat_stream", lambda **kwargs: iter(["original"]))
    first = client.post("/api/chat/stream", json=payload())
    calls = []

    def interrupted(**kwargs):
        calls.append(kwargs)
        yield "partial retry"
        from services.chat_lifecycle import cancel_chat_turn

        active = db_session.query(ChatTurn).filter_by(status="generating").one()
        cancel_chat_turn(
            db_session,
            user_id=active.user_id,
            session_id="conversation",
            request_id=active.request_id,
        )

    monkeypatch.setattr("routers.chat.chat_stream", interrupted)
    retry = client.post(
        "/api/chat/stream", json=payload(regenerate_message_id=message_ids(first)["ai"])
    )
    assert "error" in retry.text
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: calls.append(kwargs) or iter(["next"])
    )
    client.post("/api/chat/stream", json=payload(user_input="follow up"))
    history = str(calls[-1]["messages"])
    assert "original" in history
    assert "partial retry" not in history
