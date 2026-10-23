import json
from pathlib import Path

import pytest

from ai.agent import ChatStreamError
from core.config import settings


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
CASES = json.loads((CONTRACTS / "fixtures/chat-streams.json").read_text())["cases"]


def core_frames(wire: str) -> list:
    frames = []
    for line in wire.splitlines():
        if not line.startswith("data:"):
            continue
        content = line.removeprefix("data:").strip()
        if content == "[DONE]":
            frames.append(content)
        else:
            payload = json.loads(content)
            if any(key in payload for key in ("msg_ids", "text", "request_state", "error")):
                frames.append(payload)
    return frames


@pytest.mark.parametrize("case", CASES, ids=[item["id"] for item in CASES])
def test_provider_matches_shared_core_frames(case, client, monkeypatch):
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
        if case["status"] == "complete":
            yield "你"
            yield "好"
        else:
            yield "部分"
            raise ChatStreamError("AI_STREAM_INCOMPLETE", "测试流中断", retryable=True)

    monkeypatch.setattr("routers.chat.chat_stream", fake_stream)
    response = client.post(
        "/api/chat/stream",
        json={
            "request_id": case["id"],
            "session_id": "contract-session",
            "topic_id": 0,
            "node_key": "normal",
            "mode": "normal",
            "user_input": "合成测试输入",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert core_frames(response.text) == core_frames(case["wire"])
    state = client.get(f"/api/chat/requests/{case['id']}")
    assert state.status_code == 200
    assert state.json()["status"] == case["status"]
    history = client.get("/api/chat/messages").json()
    assert (
        next(message["content"] for message in history if message["role"] == "ai") == case["text"]
    )
