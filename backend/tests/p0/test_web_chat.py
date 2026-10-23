import json
import uuid

import pytest
from pydantic import ValidationError

from core.config import settings
from models import ChatMessage, ChatTurn, Topic, WebSearchQuota
from routers import chat
from schemas.web_search import WebSnapshot
from services.chat_lifecycle import begin_chat_turn, cancel_chat_turn, finish_chat_turn
from services.web_search import empty_web_snapshot
from services.web_search_quota import reserve_web_queries


@pytest.fixture(autouse=True)
def web_model(monkeypatch):
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "web-test",
                    "name": "Web test",
                    "model": "web-model",
                    "api_key": "test",
                    "base_url": "https://example.test/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "web-test")
    monkeypatch.setattr(settings, "web_search_enabled", False)
    monkeypatch.setattr(settings, "tavily_api_key", "")
    monkeypatch.setattr(settings, "web_search_daily_query_limit", 100)
    monkeypatch.setattr(settings, "web_search_global_daily_query_limit", 1000)


def request(**updates):
    return {
        "request_id": str(uuid.uuid4()),
        "session_id": "web-session",
        "node_key": "normal",
        "topic_id": 0,
        "user_input": "现在有什么变化？",
        "mode": "normal",
        **updates,
    }


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")
    ]


def ready_web():
    web = empty_web_snapshot("auto", "ready")
    web.update(
        {
            "searched_at": "2026-09-30T12:00:00Z",
            "queries": ["发布说明"],
            "decision": {
                "need_search": True,
                "reason_code": "current_information",
                "freshness": "month",
            },
            "sources": [
                {
                    "id": "s1",
                    "title": "发布说明",
                    "url": "https://example.com/releases",
                    "domain": "example.com",
                    "excerpt": "新版本增加了 A 功能。",
                    "published_at": None,
                    "retrieved_at": "2026-09-30T12:00:00Z",
                }
            ],
        }
    )
    return web


def install_search(monkeypatch, calls):
    def fake(**kwargs):
        calls.append(kwargs)
        kwargs["check_active"]()
        assert kwargs["reserve_search"](1)
        yield {"type": "web_sources", "web": ready_web(), "final": False}

    monkeypatch.setattr(chat, "iter_web_search", fake)


def test_server_owns_web_policy_and_rejects_client_override():
    assert chat.ChatRequest(**request()).web_mode == "auto"
    assert chat.ChatRequest(**request(kind="node_overview", mode="socratic")).web_mode == "off"
    assert "web_mode" not in chat.ChatRequest.model_json_schema()["properties"]
    assert "web_mode" not in chat.ChatRequest(**request()).model_dump()
    for mode in ("auto", "off", None):
        with pytest.raises(ValidationError):
            chat.ChatRequest(**request(web_mode=mode))


def test_capabilities_expose_no_credentials(client, monkeypatch):
    assert client.get("/api/chat/capabilities").json()["web_search"]["available"] is False
    monkeypatch.setattr(settings, "web_search_enabled", True)
    monkeypatch.setattr(settings, "tavily_api_key", "never-expose-me")
    response = client.get("/api/chat/capabilities")
    assert response.json() == {"web_search": {"available": True, "mode": "auto"}}
    assert "never-expose-me" not in response.text


def test_sources_persist_before_terminal_and_replay_without_search(client, db_session, monkeypatch):
    searches, answers = [], []
    install_search(monkeypatch, searches)
    monkeypatch.setattr(
        chat,
        "chat_stream",
        lambda **kwargs: answers.append(kwargs) or iter(["增加了 A。[[source:s1]]"]),
    )
    payload = request()
    first = client.post("/api/chat/stream", json=payload)
    replay = client.post("/api/chat/stream", json=payload)
    assert first.status_code == replay.status_code == 200
    assert len(searches) == len(answers) == 1
    assert searches[0]["web_mode"] == "auto"
    for response in (first, replay):
        emitted = events(response)
        complete = next(
            i
            for i, event in enumerate(emitted)
            if event.get("request_state", {}).get("status") == "complete"
        )
        final = next(
            i
            for i, event in enumerate(emitted)
            if event.get("type") == "web_sources" and event["final"]
        )
        assert final < complete
        source_event = emitted[final]
        assert source_event["request_id"] == payload["request_id"]
        assert source_event["ai_message_id"] == emitted[0]["msg_ids"]["ai"]
        assert source_event["web"]["cited_source_ids"] == ["s1"]
    message = db_session.query(ChatMessage).filter_by(role="ai").one()
    assert message.metadata_json["web"]["sources"][0]["url"] == "https://example.com/releases"
    assert message.metadata_json["web"]["cited_source_ids"] == ["s1"]
    assert {q.used_queries for q in db_session.query(WebSearchQuota)} == {1}
    history = client.get("/api/chat/messages").json()
    assert next(m for m in history if m["role"] == "ai")["metadata"]["web"]["cited_source_ids"] == [
        "s1"
    ]
    changed = client.post("/api/chat/stream", json={**payload, "user_input": "换一个问题"})
    assert changed.status_code == 409
    assert changed.json()["code"] == "CHAT_REQUEST_CONFLICT"


def test_overview_disables_search_even_when_server_enabled(
    client, db_session, auth_user, monkeypatch
):
    monkeypatch.setattr(settings, "web_search_enabled", True)
    monkeypatch.setattr(settings, "tavily_api_key", "offline-test-key")
    topic = Topic(user_id=auth_user.id, title="递归")
    db_session.add(topic)
    db_session.commit()
    monkeypatch.setattr(
        "services.web_search.generate_structured",
        lambda *a, **kw: pytest.fail("off must not decide"),
    )
    monkeypatch.setattr(
        chat, "reserve_web_queries", lambda *a, **kw: pytest.fail("off must not reserve")
    )
    monkeypatch.setattr(chat, "chat_stream", lambda **kw: iter(["解释递归。 "]))
    response = client.post(
        "/api/chat/stream",
        json=request(kind="topic_overview", mode="socratic", topic_id=topic.id),
    )
    assert response.status_code == 200
    assert any(e.get("request_state", {}).get("status") == "complete" for e in events(response))
    assert (
        next(e for e in events(response) if e.get("type") == "web_sources")["web"]["status"]
        == "off"
    )


def test_unavailable_warns_without_terminating_answer(client, monkeypatch):
    captured = []
    monkeypatch.setattr(
        chat, "chat_stream", lambda **kw: captured.append(kw) or iter(["目前无法核实最新情况。 "])
    )
    response = client.post("/api/chat/stream", json=request())
    emitted = events(response)
    assert any(
        e.get("type") == "web_warning" and e["warning"]["code"] == "WEB_UNAVAILABLE"
        for e in emitted
    )
    assert any(e.get("request_state", {}).get("status") == "complete" for e in emitted)
    assert not any("error" in e for e in emitted)
    assert captured


def test_model_error_payload_is_not_exposed_to_logs_or_client(client, monkeypatch, caplog):
    secret = "provider-echoed-private-value"

    def failing(**kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(chat, "chat_stream", failing)
    response = client.post("/api/chat/stream", json=request())
    assert secret not in caplog.text
    assert secret not in response.text
    assert "AI_STREAM_ERROR" in response.text


def test_unknown_citation_warns_without_fabricating_source(client, db_session, monkeypatch):
    install_search(monkeypatch, [])
    monkeypatch.setattr(
        chat, "chat_stream", lambda **kw: iter(["引用错误。[[source:s5]] 有效。[[source:s1]]"])
    )
    response = client.post("/api/chat/stream", json=request())
    assert any(e.get("warning", {}).get("code") == "WEB_CITATION_INVALID" for e in events(response))
    web = db_session.query(ChatMessage).filter_by(role="ai").one().metadata_json["web"]
    assert web["cited_source_ids"] == ["s1"]
    assert web["metrics"]["invalid_citations"] == 1


def test_cancel_during_search_prevents_late_sources_and_answer(
    client, db_session, auth_user, monkeypatch
):
    def cancelling(**kwargs):
        web = empty_web_snapshot("auto", "searching")
        yield {"type": "web_status", "status": "searching", "web": web}
        cancel_chat_turn(
            db_session,
            user_id=auth_user.id,
            session_id="web-session",
            request_id=kwargs["request_id"],
        )
        kwargs["check_active"]()
        yield {"type": "web_sources", "web": ready_web(), "final": False}

    monkeypatch.setattr(chat, "iter_web_search", cancelling)
    monkeypatch.setattr(chat, "chat_stream", lambda **kw: pytest.fail("cancel must not fall back"))
    response = client.post("/api/chat/stream", json=request())
    assert db_session.query(ChatTurn).one().status == "interrupted"
    message = db_session.query(ChatMessage).filter_by(role="ai").one()
    assert message.metadata_json["web"]["sources"] == []
    assert not any(e.get("web", {}).get("sources") for e in events(response))


def test_failed_regeneration_keeps_original_sources(client, db_session, monkeypatch):
    searches = []
    install_search(monkeypatch, searches)
    monkeypatch.setattr(chat, "chat_stream", lambda **kw: iter(["原答案。[[source:s1]]"]))
    first = client.post("/api/chat/stream", json=request())
    original_id = events(first)[0]["msg_ids"]["ai"]
    monkeypatch.setattr(chat, "chat_stream", lambda **kw: iter([]))
    second = client.post("/api/chat/stream", json=request(regenerate_message_id=original_id))
    assert any(e.get("error", {}).get("code") == "AI_EMPTY_RESPONSE" for e in events(second))
    messages = client.get("/api/chat/messages").json()
    answers = [m for m in messages if m["role"] == "ai"]
    assert len(answers) == 1 and answers[0]["id"] == original_id
    assert answers[0]["metadata"]["web"]["cited_source_ids"] == ["s1"]


def test_successful_regeneration_replaces_answer_and_sources(client, monkeypatch):
    searches = []
    install_search(monkeypatch, searches)
    monkeypatch.setattr(chat, "chat_stream", lambda **kw: iter(["原答案。[[source:s1]]"]))
    first = client.post("/api/chat/stream", json=request())
    old_id = events(first)[0]["msg_ids"]["ai"]
    monkeypatch.setattr(chat, "chat_stream", lambda **kw: iter(["新答案。[[source:s1]]"]))
    response = client.post("/api/chat/stream", json=request(regenerate_message_id=old_id))
    new_id = events(response)[0]["msg_ids"]["ai"]
    messages = client.get("/api/chat/messages").json()
    answers = [m for m in messages if m["role"] == "ai"]
    assert len(answers) == 1 and answers[0]["id"] == new_id != old_id
    assert answers[0]["metadata"]["web"]["cited_source_ids"] == ["s1"]


def start(db, user_id, request_id):
    return begin_chat_turn(
        db,
        user_id=user_id,
        topic_id=None,
        session_id=request_id,
        node_key="normal",
        user_input="question",
        mode="normal",
        request_id=request_id,
        model_id="web-test",
    )


def reserve(db, user_id, turn, queries):
    return reserve_web_queries(
        db,
        user_id=user_id,
        request_id=turn.request_id,
        generation_token=turn.generation_token,
        queries=queries,
    )


def test_quota_is_atomic_idempotent_and_survives_message_deletion(
    db_session, auth_user, monkeypatch
):
    user_id = auth_user.id
    monkeypatch.setattr(settings, "web_search_daily_query_limit", 2)
    first = start(db_session, auth_user.id, "one")
    assert reserve(db_session, auth_user.id, first.turn, 2)
    assert reserve(db_session, auth_user.id, first.turn, 2)
    second = start(db_session, auth_user.id, "two")
    assert not reserve(db_session, auth_user.id, second.turn, 1)
    assert {q.used_queries for q in db_session.query(WebSearchQuota)} == {2}
    db_session.query(ChatMessage).delete(synchronize_session=False)
    db_session.commit()
    db_session.expunge_all()
    third = start(db_session, user_id, "three")
    assert not reserve(db_session, user_id, third.turn, 1)
    assert {q.used_queries for q in db_session.query(WebSearchQuota)} == {2}


def test_global_quota_rolls_back_user_reservation(db_session, auth_user, monkeypatch):
    monkeypatch.setattr(settings, "web_search_global_daily_query_limit", 1)
    turn = start(db_session, auth_user.id, "quota").turn
    assert not reserve(db_session, auth_user.id, turn, 2)
    assert all(q.used_queries == 0 for q in db_session.query(WebSearchQuota))
    assert reserve(db_session, auth_user.id, turn, 1)


def test_cancelled_turn_cannot_reserve_or_write_sources(db_session, auth_user):
    started = start(db_session, auth_user.id, "cancel")
    before = WebSnapshot.model_validate(started.ai_message.metadata_json["web"])
    assert before.status == "deciding" and before.config_version
    cancel_chat_turn(db_session, user_id=auth_user.id, request_id="cancel", session_id="cancel")
    db_session.refresh(started.ai_message)
    after = WebSnapshot.model_validate(started.ai_message.metadata_json["web"])
    assert after.status == "failed" and after.config_version == before.config_version
    assert not reserve(db_session, auth_user.id, started.turn, 1)
    assert not finish_chat_turn(
        db_session,
        user_id=auth_user.id,
        request_id="cancel",
        generation_token=started.turn.generation_token,
        content="late",
        status="complete",
        web=ready_web(),
    )
    db_session.refresh(started.ai_message)
    assert not started.ai_message.metadata_json["web"]["sources"]
