"""A shared native model catalog and selection contract, without external model calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import ai_client
from core.config import settings
from core.deps import get_current_user
from core.user_llm import encrypt_api_key, load_user_profiles
from models import ChatMessage, ChatTurn, User, UserLLMProfile


DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/model-selection.json").read_text()
)


@pytest.fixture()
def selection_provider(monkeypatch, db_session, auth_user):
    monkeypatch.setattr(ai_client, "_custom_profiles", {})
    environment = [
        {key: value for key, value in row.items() if key != "source"}
        | {
            "api_key": "synthetic-only",
            "base_url": "https://environment.example.test/v1",
            "tokenizer_encoding": "utf8_bytes",
        }
        for row in DATA["catalog"]["models"]
        if row["source"] == "environment"
    ]
    monkeypatch.setattr(settings, "llm_models", json.dumps(environment))
    monkeypatch.setattr(settings, "llm_default_model_id", DATA["default_id"])
    monkeypatch.setattr(settings, "web_search_enabled", False)
    custom = DATA["catalog"]["models"][-1]
    own = UserLLMProfile(
        id=custom["id"].removeprefix("custom:"),
        user_id=auth_user.id,
        api_key_encrypted=encrypt_api_key("synthetic-private-key"),
        **{key: value for key, value in custom.items() if key not in {"id", "source"}},
    )
    other = User(username="model-other", email="other@example.test", hashed_password="unused")
    db_session.add_all([own, other])
    db_session.flush()
    foreign = UserLLMProfile(
        id="00000000-0000-4000-8000-000000000002",
        user_id=other.id,
        name="其他账号模型",
        model="foreign-model",
        base_url="https://foreign.example.test/v1",
        api_key_encrypted=encrypt_api_key("synthetic-other-key"),
    )
    db_session.add(foreign)
    db_session.commit()
    load_user_profiles(db_session, other.id)
    calls = []

    def stream(**arguments):
        calls.append(arguments)
        yield "合成模型响应。"

    monkeypatch.setattr("routers.chat.chat_stream", stream)
    return calls, foreign.public_id


def test_catalog_matches_shared_projection_and_hides_other_accounts_and_credentials(
    client, selection_provider
):
    response = client.get("/api/llm/models")
    assert response.status_code == 200
    assert response.json() == DATA["catalog"]
    assert DATA["default_id"] != response.json()["models"][0]["id"]
    for forbidden in ("synthetic-private-key", "synthetic-only", "api_key", "foreign-model"):
        assert forbidden not in response.text
    assert all(
        "base_url" not in item
        for item in response.json()["models"]
        if item["source"] == "environment"
    )


def test_catalog_requires_authentication(app, client, selection_provider):
    app.dependency_overrides.pop(get_current_user)
    assert client.get("/api/llm/models").status_code == 401


@pytest.mark.parametrize("case", DATA["requests"], ids=lambda value: value["name"])
def test_selection_uses_profile_identity_and_server_default_including_cold_custom_cache(
    client, db_session, selection_provider, case
):
    calls, _ = selection_provider
    # The current user's private profile is not cached by listing. The chat route loads it.
    assert DATA["catalog"]["models"][-1]["id"] not in ai_client._custom_profiles
    assert client.post("/api/chat/stream", json=case["request"]).status_code == 200
    turn = db_session.query(ChatTurn).filter_by(request_id=case["request"]["request_id"]).one()
    assert turn.model_id == case["resolved_model"] and turn.status == "complete"
    assert len(calls) == 1
    assert calls[0]["model_id"] == case["resolved_model"]
    assert client.post("/api/chat/stream", json=case["request"]).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("reason", ["unknown", "foreign", "deleted", "invalid-config"])
def test_unavailable_selection_is_typed_before_creating_a_turn(
    client, db_session, selection_provider, monkeypatch, reason
):
    calls, foreign = selection_provider
    payload = {**DATA["requests"][0]["request"]}
    if reason == "invalid-config":
        monkeypatch.setattr(settings, "llm_models", "[]")
    else:
        selected = {
            "unknown": "not-configured",
            "foreign": foreign,
            "deleted": DATA["catalog"]["models"][-1]["id"],
        }[reason]
        if reason == "deleted":
            assert client.delete(f"/api/llm/models/{selected}").status_code == 200
        payload["model"] = selected
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == DATA["unavailable"]["status"]
    assert response.json() == DATA["unavailable"]["payload"]
    assert not calls and db_session.query(ChatTurn).count() == 0
    assert db_session.query(ChatMessage).count() == 0
    # The existing cancellation endpoint can durably fence this request after an explicit rejection.
    cancelled = client.post(
        "/api/chat/cancel", json={key: payload[key] for key in ("request_id", "session_id")}
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "interrupted"


def test_regeneration_can_use_current_selection_without_changing_original_question(
    client, db_session, selection_provider
):
    calls, _ = selection_provider
    original = DATA["requests"][0]["request"]
    assert client.post("/api/chat/stream", json=original).status_code == 200
    before = db_session.query(ChatTurn).filter_by(request_id=original["request_id"]).one()
    request = {
        **original,
        "request_id": "model-regenerate",
        "model": "env:first",
        "regenerate_message_id": before.ai_message_id,
    }
    assert client.post("/api/chat/stream", json=request).status_code == 200
    after = db_session.query(ChatTurn).filter_by(request_id=request["request_id"]).one()
    assert after.user_message_id == before.user_message_id and after.model_id == "env:first"
    assert [call["model_id"] for call in calls] == [DATA["default_id"], "env:first"]
    assert db_session.query(ChatMessage).filter_by(role="user").count() == 1


def test_suggestions_share_selection_and_unavailable_error_contract(
    client, selection_provider, monkeypatch
):
    selected = []

    def factory(model):
        selected.append(model)
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_: SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content='{"suggestions":["合成建议？"]}')
                            )
                        ]
                    )
                )
            )
        )

    monkeypatch.setattr("routers.chat.get_ai_client", factory)
    params = {"mode": "normal", "session_id": "model-suggestions", "model": "env:first"}
    response = client.get("/api/chat/suggestions", params=params)
    assert response.status_code == 200 and response.json()["source"] == "ai"
    assert selected == ["env:first"]
    response = client.get("/api/chat/suggestions", params={**params, "model": "missing"})
    assert response.status_code == 422 and response.json() == DATA["unavailable"]["payload"]
    assert selected == ["env:first"]
