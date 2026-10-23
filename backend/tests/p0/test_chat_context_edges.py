import json
import uuid

import pytest

from core.config import settings
from models import ChatMessage, ChatSession, ChatTurn, User
from services.chat_lifecycle import cancel_chat_turn


@pytest.fixture(autouse=True)
def edge_model(monkeypatch):
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "edge-test",
                    "name": "Edge test",
                    "model": "edge-test-model",
                    "api_key": "test",
                    "base_url": "https://example.test/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "edge-test")


def request(**updates):
    value = {
        "request_id": str(uuid.uuid4()),
        "session_id": "edge-session",
        "node_key": "normal",
        "topic_id": 0,
        "mode": "normal",
        "user_input": "edge question",
    }
    value.update(updates)
    return value


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")
    ]


def test_cancelled_stream_reports_same_terminal_state_as_database(
    client, db_session, auth_user, monkeypatch
):
    payload = request()

    from routers import chat

    original_refresh = chat.refresh_generation_lease
    cancelled = False

    def refresh_with_cancel(db, **kwargs):
        nonlocal cancelled
        # Model streaming runs in a worker. Simulate the external cancellation
        # at the main generator's first checkpoint, where this test Session is
        # owned, instead of concurrently flushing it from the model worker.
        if kwargs.get("content") and not cancelled:
            cancelled = True
            cancel_chat_turn(
                db,
                user_id=auth_user.id,
                session_id="edge-session",
                request_id=payload["request_id"],
            )
        return original_refresh(db, **kwargs)

    monkeypatch.setattr(chat, "refresh_generation_lease", refresh_with_cancel)
    monkeypatch.setattr(
        chat, "chat_stream", lambda **kwargs: iter(["already visible", "next token after stop"])
    )
    response = client.post("/api/chat/stream", json=payload)
    turn = db_session.query(ChatTurn).one()
    assert turn.status == "interrupted"
    states = [
        item["request_state"]["status"] for item in events(response) if "request_state" in item
    ]
    assert states == [turn.status]


def test_model_waits_never_hold_request_database_transaction(client, db_session, monkeypatch):
    def streamed(**kwargs):
        assert not db_session.in_transaction()
        yield "first"
        assert not db_session.in_transaction()
        yield "last"
        assert not db_session.in_transaction()

    monkeypatch.setattr("routers.chat.chat_stream", streamed)
    response = client.post("/api/chat/stream", json=request())
    assert response.status_code == 200
    assert not any("error" in item for item in events(response))
    assert db_session.query(ChatTurn).one().status == "complete"


def test_empty_normal_reply_is_failed_and_never_scheduled_for_summary(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("routers.chat.chat_stream", lambda **kwargs: iter([" ", "\n"]))
    monkeypatch.setattr(
        "routers.chat.schedule_chat_summary",
        lambda **kwargs: pytest.fail("empty reply cannot schedule a summary"),
    )
    response = client.post("/api/chat/stream", json=request())
    assert db_session.query(ChatTurn).one().status == "failed"
    assert db_session.query(ChatSession).one().active_request_id is None
    assert any(
        item.get("error", {}).get("code") == "AI_EMPTY_RESPONSE" for item in events(response)
    )


def test_user_with_same_session_name_cannot_enter_context(client, db_session, monkeypatch):
    other = User(
        username="context-edge-other",
        email="context-edge-other@example.test",
        hashed_password="unused",
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(
        ChatMessage(
            user_id=other.id,
            session_id="edge-session",
            topic_id=None,
            role="ai",
            content="private other user secret",
            mode="normal",
            node_key="normal",
        )
    )
    db_session.commit()
    captured = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captured.append(kwargs) or iter(["answer"])
    )
    response = client.post("/api/chat/stream", json=request())
    assert response.status_code == 200
    assert "private other user secret" not in str(captured[0]["prepared_messages"])


def test_regeneration_before_first_summary_keeps_selected_model_for_rebuild(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("routers.chat.chat_stream", lambda **kwargs: iter(["answer"]))
    first = client.post("/api/chat/stream", json=request())
    ids = next(item["msg_ids"] for item in events(first) if "msg_ids" in item)
    second = client.post("/api/chat/stream", json=request(regenerate_message_id=ids["ai"]))
    assert second.status_code == 200
    session = db_session.query(ChatSession).one()
    assert session.summary_status == "pending"
    assert session.summary_model == "edge-test"


def test_quote_already_in_recent_history_is_sent_once(client, monkeypatch):
    captures = []
    text = "Unique precise answer requested as a quote."
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captures.append(kwargs) or iter([text])
    )
    first = client.post("/api/chat/stream", json=request())
    ids = next(item["msg_ids"] for item in events(first) if "msg_ids" in item)
    response = client.post(
        "/api/chat/stream",
        json=request(
            user_input="Explain the quote", quote_source_id=ids["ai"], quote_text="precise answer"
        ),
    )
    assert response.status_code == 200
    assert sum(message["content"].count(text) for message in captures[-1]["prepared_messages"]) == 1


def test_unsummarized_development_history_survives_first_managed_summary(
    client, db_session, auth_user, monkeypatch
):
    for role, text in [("user", "legacy user detail"), ("ai", "legacy answer detail")]:
        db_session.add(
            ChatMessage(
                user_id=auth_user.id,
                session_id="edge-session",
                topic_id=None,
                role=role,
                content=text,
                mode="normal",
                node_key="normal",
                metadata_json={"status": "complete"},
            )
        )
    db_session.commit()
    captures = []
    monkeypatch.setattr(
        "routers.chat.chat_stream",
        lambda **kwargs: captures.append(kwargs) or iter(["managed answer"]),
    )
    client.post("/api/chat/stream", json=request(user_input="managed question"))
    session = db_session.query(ChatSession).one()
    turn = db_session.query(ChatTurn).one()
    session.summary_json = {
        "goal": "managed discussion only",
        "source_message_ids": [turn.user_message_id, turn.ai_message_id],
    }
    session.summary_through_turn_id = turn.id
    session.summary_source_version = session.content_version
    session.summary_status = "ready"
    db_session.commit()
    client.post("/api/chat/stream", json=request(user_input="follow up"))
    assert "legacy user detail" in str(captures[-1]["prepared_messages"])
    assert "legacy answer detail" in str(captures[-1]["prepared_messages"])


def test_output_limit_retains_partial_for_continuation_without_summarizing(
    client, db_session, monkeypatch
):
    from ai.agent import ChatStreamError

    def limited(**kwargs):
        yield "partial explanation"
        raise ChatStreamError(
            "AI_OUTPUT_LIMIT", "请输入继续", retryable=False, finish_reason="length"
        )

    monkeypatch.setattr("routers.chat.chat_stream", limited)
    first = client.post("/api/chat/stream", json=request())
    assert db_session.query(ChatTurn).one().status == "interrupted"
    assert db_session.query(ChatSession).one().summary_status == "idle"
    assert any(
        item.get("error", {}).get("code") == "AI_OUTPUT_LIMIT"
        and item["error"]["retryable"] is False
        for item in events(first)
    )
    captures = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captures.append(kwargs) or iter(["continued"])
    )
    client.post("/api/chat/stream", json=request(user_input="继续"))
    assert "partial explanation" in str(captures[0]["prepared_messages"])
    assert "尚未完成" in str(captures[0]["prepared_messages"])


@pytest.mark.parametrize("summary_succeeds", [True, False])
def test_hard_limit_compacts_once_or_reports_retry_without_silently_omitting_history(
    client, db_session, monkeypatch, summary_succeeds
):
    from services.chat_context import PreparedChatContext

    assemblies = []
    jobs = []
    captures = []

    def assembled(*args, **kwargs):
        assemblies.append(kwargs)
        return PreparedChatContext(
            [{"role": "user", "content": "all necessary context"}],
            [],
            [],
            100,
            True,
            len(assemblies) == 1 or not summary_succeeds,
        )

    def compact(factory, **kwargs):
        assert not db_session.in_transaction()
        jobs.append(kwargs)
        return True

    monkeypatch.setattr("routers.chat.assemble_chat_context", assembled)
    monkeypatch.setattr("routers.chat.run_one_summary_job", compact)
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captures.append(kwargs) or iter(["answer"])
    )
    response = client.post("/api/chat/stream", json=request())
    output = events(response)
    assert len(jobs) == 1
    assert jobs[0] == {"target_session_id": db_session.query(ChatSession).one().id, "force": True}
    assert any(item.get("type") == "context_compacting" for item in output)
    if summary_succeeds:
        assert any(item.get("type") == "context_ready" for item in output)
        assert len(captures) == 1
        assert db_session.query(ChatTurn).one().status == "complete"
    else:
        assert captures == []
        assert any(item.get("error", {}).get("code") == "CHAT_CONTEXT_NOT_READY" for item in output)
        assert db_session.query(ChatTurn).one().status == "failed"


def test_regeneration_reuses_only_summary_ending_before_replaced_answer(
    client, db_session, monkeypatch
):
    captures = []
    monkeypatch.setattr(
        "routers.chat.chat_stream", lambda **kwargs: captures.append(kwargs) or iter(["old answer"])
    )
    client.post("/api/chat/stream", json=request(user_input="earlier question"))
    second = client.post("/api/chat/stream", json=request(user_input="latest question"))
    ids = next(item["msg_ids"] for item in events(second) if "msg_ids" in item)
    session = db_session.query(ChatSession).one()
    first_turn = db_session.query(ChatTurn).order_by(ChatTurn.id).first()
    session.summary_json = {"goal": "safe earlier summary"}
    session.summary_source_version = session.content_version
    session.summary_through_turn_id = first_turn.id
    db_session.commit()
    regenerated = client.post(
        "/api/chat/stream",
        json=request(user_input="latest question", regenerate_message_id=ids["ai"]),
    )
    assert regenerated.status_code == 200
    assert not any("error" in item for item in events(regenerated))
    prompt = str(captures[-1]["prepared_messages"])
    assert "safe earlier summary" in prompt
    assert "earlier question" not in prompt
    assert "old answer" not in prompt
    assert "latest question" in prompt


def test_real_budget_overflow_uses_durable_summary_then_sends_complete_context(
    client, db_session, auth_user, monkeypatch
):
    from types import SimpleNamespace
    from core.context_budget import ensure_fits
    from services.chat_summaries import SessionSummary, run_one_summary_job

    session = ChatSession(user_id=auth_user.id, session_id="edge-session", mode="normal")
    db_session.add(session)
    db_session.flush()
    for index in range(26):
        args = dict(
            user_id=auth_user.id, session_id=session.session_id, mode="normal", node_key="normal"
        )
        question = ChatMessage(**args, role="user", content=f"earlier-question-{index}")
        answer = ChatMessage(**args, role="ai", content=f"earlier-answer-{index}:" + "x" * 10_000)
        db_session.add_all([question, answer])
        db_session.flush()
        db_session.add(
            ChatTurn(
                chat_session_id=session.id,
                user_id=auth_user.id,
                request_id=str(uuid.uuid4()),
                request_fingerprint="seed",
                user_message_id=question.id,
                ai_message_id=answer.id,
                status="complete",
                model_id="edge-test",
                node_key="normal",
                generation_token=str(uuid.uuid4()),
                source_version=1,
            )
        )
    db_session.commit()
    summaries = []

    def summarize(schema, messages, context):
        assert not db_session.in_transaction()
        source = json.loads(messages[-1]["content"])
        summaries.append(source)
        return SimpleNamespace(
            value=SessionSummary(
                goal="earlier discussion preserved",
                node_keys=["normal"],
                source_message_ids=[mid for turn in source["turns"] for mid in turn["message_ids"]],
            ),
            token_usage=100,
        )

    monkeypatch.setattr(
        "routers.chat.run_one_summary_job",
        lambda factory, **kwargs: run_one_summary_job(factory, summarize, **kwargs),
    )
    captures = []
    monkeypatch.setattr(
        "routers.chat.chat_stream",
        lambda **kwargs: captures.append(kwargs) or iter(["final answer"]),
    )
    response = client.post("/api/chat/stream", json=request())
    assert not any("error" in item for item in events(response))
    assert len(summaries) == 1
    assert len(captures) == 1
    prepared = captures[0]["prepared_messages"]
    ensure_fits(prepared, "edge-test")
    assert "earlier discussion preserved" in str(prepared)
    assert "earlier-answer-25:" in str(prepared)
    assert "earlier-answer-0:" not in str(prepared)
    assert db_session.query(ChatMessage).count() == 54
