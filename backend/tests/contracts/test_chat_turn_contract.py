"""Provider checks for the native stable-ID / cancellation / exact-history recovery workflow."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai.agent import ChatStreamError
from core.config import settings
from models import ChatMessage
from routers.chat import ChatRequest


DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/chat-turns.json").read_text()
)
REQUEST = DATA["request"]


@pytest.fixture()
def generation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "contract-model",
                    "name": "Contract",
                    "model": "contract-model",
                    "api_key": "test-key",
                    "base_url": "http://127.0.0.1:1/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "contract-model")
    monkeypatch.setattr(settings, "web_search_enabled", False)

    def fake_stream(**_arguments):
        calls.append(1)
        yield "你好，"
        yield "世界🙂"

    monkeypatch.setattr("routers.chat.chat_stream", fake_stream)
    return calls


@pytest.mark.parametrize("interrupted", [False, True])
def test_send_recover_exact_messages_and_cancel_terminal(
    client, generation, monkeypatch, interrupted
):
    if interrupted:

        def partial(**_arguments):
            generation.append(1)
            yield "部分回答"
            raise ChatStreamError("AI_STREAM_INCOMPLETE", "合成中断", retryable=True)

        monkeypatch.setattr("routers.chat.chat_stream", partial)
    response = client.post("/api/chat/stream", json=REQUEST)
    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    state = client.get(f"/api/chat/requests/{REQUEST['request_id']}")
    assert state.status_code == 200
    value = state.json()
    assert value["request_id"] == REQUEST["request_id"]
    assert value["session_id"] == REQUEST["session_id"]
    assert value["status"] == ("interrupted" if interrupted else "complete")
    for role, content in [
        ("user", REQUEST["user_input"]),
        ("ai", "部分回答" if interrupted else DATA["messages"][1]["content"]),
    ]:
        identifier = value["msg_ids"][role]
        page = client.get(
            "/api/chat/session-messages",
            params={
                "session_id": REQUEST["session_id"],
                "snapshot_id": identifier,
                "limit": 1,
            },
        ).json()
        assert page["snapshot_id"] == identifier
        assert len(page["items"]) == 1
        assert page["items"][0]["id"] == identifier
        assert page["items"][0]["role"] == role
        assert page["items"][0]["content"] == content
    cancel = client.post(
        "/api/chat/cancel",
        json={
            "request_id": REQUEST["request_id"],
            "session_id": REQUEST["session_id"],
        },
    )
    assert cancel.json() == {"status": value["status"], "msg_ids": value["msg_ids"]}
    assert client.post("/api/chat/stream", json=REQUEST).status_code == 200
    assert len(generation) == 1  # Recovery / idempotent replay never starts another provider call.


def test_cancel_before_arrival_is_durable_and_status_404_is_not_completion(client, generation):
    pending = {key: REQUEST[key] for key in ("request_id", "session_id")}
    missing = client.get(f"/api/chat/requests/{REQUEST['request_id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "CHAT_REQUEST_NOT_FOUND"
    assert client.post("/api/chat/cancel", json=pending).json() == {"status": "interrupted"}
    delayed = client.post("/api/chat/stream", json=REQUEST)
    assert delayed.status_code == 409
    assert delayed.json()["code"] == "CHAT_REQUEST_CANCELLED"
    assert generation == []


def test_exact_history_lookup_can_return_a_neighbour_after_deletion(client, generation, db_session):
    assert client.post("/api/chat/stream", json=REQUEST).status_code == 200
    ids = client.get(f"/api/chat/requests/{REQUEST['request_id']}").json()["msg_ids"]
    db_session.query(ChatMessage).filter_by(id=ids["ai"]).delete()
    db_session.commit()
    page = client.get(
        "/api/chat/session-messages",
        params={
            "session_id": REQUEST["session_id"],
            "snapshot_id": ids["ai"],
            "limit": 1,
        },
    ).json()
    assert page["snapshot_id"] == ids["ai"]
    assert [row["id"] for row in page["items"]] == [ids["user"]]


def test_native_request_shape_preserves_whitespace_and_scalar_limit():
    assert ChatRequest.model_validate(REQUEST).user_input == REQUEST["user_input"]
    assert (
        len(ChatRequest.model_validate({**REQUEST, "user_input": "🙂" * 5000}).user_input) == 5000
    )
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({**REQUEST, "user_input": "🙂" * 5001})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({**REQUEST, "web_mode": "auto"})
