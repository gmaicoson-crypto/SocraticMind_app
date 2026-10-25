"""Provider feedback is durable per attempt and safe across history, replay and accounts."""

import json

import pytest

from core.deps import get_current_user
from models import ChatMessage, User
from tests.contracts.test_chat_turn_contract import REQUEST, generation as generation
from tests.feedback_cases import DATA, PRIVATE_DETAIL, provider_error


def stream_events(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


@pytest.mark.parametrize("case", DATA["errors"], ids=lambda case: case["kind"])
def test_model_errors_survive_status_history_and_replay_without_private_detail(
    client, generation, monkeypatch, case, caplog
):
    def stream(**arguments):
        generation.append(1)
        yield "合成部分回答"
        arguments["on_usage"](DATA["reported_usage"] | {"private": PRIVATE_DETAIL})
        raise provider_error(case["kind"])

    monkeypatch.setattr("routers.chat.chat_stream", stream)
    response = client.post("/api/chat/stream", json=REQUEST)
    assert response.status_code == 200
    expected = {key: case[key] for key in ("code", "message", "retryable")}
    assert {"error": expected} in stream_events(response)
    state = client.get(f"/api/chat/requests/{REQUEST['request_id']}").json()
    assert state["status"] == case["status"] and state["error"] == expected
    assert state["error_code"] == case["code"] and state["usage"] == DATA["reported_usage"]
    history = client.get(
        "/api/chat/session-messages", params={"session_id": REQUEST["session_id"]}
    ).json()
    answer = next(item for item in history["items"] if item["id"] == state["msg_ids"]["ai"])
    assert answer["content"] == "合成部分回答"
    assert answer["metadata"]["usage"] == DATA["reported_usage"]
    assert answer["metadata"]["error_code"] == case["code"]
    replay = client.post("/api/chat/stream", json=REQUEST)
    assert {"error": expected} in stream_events(replay)
    assert len(generation) == 1
    for data in (response.text, json.dumps(state), json.dumps(history), replay.text, caplog.text):
        assert "synthetic-private-key" not in data and "/private" not in data


@pytest.mark.parametrize("case", DATA["usage_cases"], ids=lambda case: case["name"])
def test_reported_and_unknown_usage_agree_in_history_status_and_cancel(
    client, generation, monkeypatch, case
):
    def stream(**arguments):
        generation.append(1)
        arguments["on_usage"](case["input"])
        yield "合成完整回答"

    monkeypatch.setattr("routers.chat.chat_stream", stream)
    assert client.post("/api/chat/stream", json=REQUEST).status_code == 200
    state = client.get(f"/api/chat/requests/{REQUEST['request_id']}").json()
    assert state["status"] == "complete" and state["error"] is None
    assert state["usage"] == case["expected"]
    history = client.get(
        "/api/chat/session-messages", params={"session_id": REQUEST["session_id"]}
    ).json()
    answer = next(item for item in history["items"] if item["role"] == "ai")
    assert answer["metadata"].get("usage") == case["expected"]
    if case["expected"] is None:
        assert "usage" not in answer["metadata"]
    cancel = client.post(
        "/api/chat/cancel", json={key: REQUEST[key] for key in ("request_id", "session_id")}
    ).json()
    assert cancel.get("usage") == case["expected"] and cancel["status"] == "complete"
    assert len(generation) == 1


def test_failed_regeneration_keeps_old_answer_but_exposes_own_attempt_usage(
    client, generation, monkeypatch, db_session
):
    assert client.post("/api/chat/stream", json=REQUEST).status_code == 200
    original = client.get(f"/api/chat/requests/{REQUEST['request_id']}").json()

    def stream(**arguments):
        arguments["on_usage"](DATA["reported_usage"])
        yield "未完成的重生成"
        raise provider_error("quota")

    monkeypatch.setattr("routers.chat.chat_stream", stream)
    request = REQUEST | {
        "request_id": "feedback-regenerate",
        "regenerate_message_id": original["msg_ids"]["ai"],
    }
    assert client.post("/api/chat/stream", json=request).status_code == 200
    state = client.get("/api/chat/requests/feedback-regenerate").json()
    assert state["status"] == "failed" and state["usage"] == DATA["reported_usage"]
    history = client.get(
        "/api/chat/session-messages", params={"session_id": REQUEST["session_id"]}
    ).json()
    assert original["msg_ids"]["ai"] in {item["id"] for item in history["items"]}
    assert state["msg_ids"]["ai"] not in {item["id"] for item in history["items"]}
    assert (
        db_session.get(ChatMessage, state["msg_ids"]["ai"]).metadata_json["usage"]
        == DATA["reported_usage"]
    )


def test_other_account_cannot_read_usage_or_turn_status(client, app, generation, db_session):
    assert client.post("/api/chat/stream", json=REQUEST).status_code == 200
    other = User(username="feedback-other", email="feedback@example.test", hashed_password="unused")
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    response = client.get(f"/api/chat/requests/{REQUEST['request_id']}")
    assert response.status_code == 404 and "usage" not in response.json()
