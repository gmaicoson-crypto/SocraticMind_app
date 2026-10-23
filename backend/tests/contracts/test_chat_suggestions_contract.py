"""Provider behavior behind the shared native suggestions fixture, using synthetic model responses."""

import json
from pathlib import Path
from types import SimpleNamespace

from models import ChatMessage
from routers import chat


DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/chat-suggestions.json").read_text()
)


def mock_provider(monkeypatch, *, failing=False):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        if failing:
            raise RuntimeError("synthetic unavailable")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(DATA["result"], ensure_ascii=False))
                )
            ]
        )

    monkeypatch.setattr(
        chat,
        "get_ai_client",
        lambda _: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    return captured


def test_normal_native_query_uses_current_context_and_normalizes_repeated_exclusions(
    client, db_session, auth_user, monkeypatch
):
    db_session.add(
        ChatMessage(
            user_id=auth_user.id,
            session_id=DATA["target"]["session_id"],
            mode="normal",
            node_key="__normal__",
            role="user",
            content="合成当前话题",
        )
    )
    db_session.commit()
    captured = mock_provider(monkeypatch)
    result = client.get(
        "/api/chat/suggestions",
        params=[
            ("mode", "normal"),
            ("session_id", DATA["target"]["session_id"]),
            *[("exclude", item) for item in DATA["exclude"]],
        ],
    )
    assert result.status_code == 200 and result.json() == DATA["result"]
    prompt = captured["messages"][0]["content"]
    assert "合成当前话题" in prompt and "已经展示过" in prompt
    assert DATA["wire_exclude"][0] in prompt and DATA["wire_exclude"][1] in prompt
    assert "🙂" * 81 not in prompt


def test_native_local_starters_and_followups_match_existing_provider_fallback(
    client, db_session, auth_user, monkeypatch
):
    mock_provider(monkeypatch, failing=True)
    for contextual in [False, True]:
        if contextual:
            db_session.add(
                ChatMessage(
                    user_id=auth_user.id,
                    session_id="fallback",
                    mode="normal",
                    node_key="__normal__",
                    role="user",
                    content="合成上下文",
                )
            )
            db_session.commit()
        result = client.get(
            "/api/chat/suggestions", params={"mode": "normal", "session_id": "fallback"}
        )
        assert result.status_code == 200
        key = "normal_followup" if contextual else "normal_new"
        assert result.json() == {"suggestions": DATA["defaults"][key][:12], "source": "fallback"}
