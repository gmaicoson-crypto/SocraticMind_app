import json
from types import SimpleNamespace

import pytest

from core import ai_client
from core.config import Settings


def test_multiline_llm_models_load_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODELS", raising=False)
    monkeypatch.delenv("LLM_DEFAULT_MODEL_ID", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        """LLM_MODELS=[
  {
    "MODEL": "first-model",
    "API_KEY": "first-key",
    "BASE_URL": "https://first.example/v1",
    "NAME": "First"
  },
  {
    "MODEL": "second-model",
    "API_KEY": "second-key",
    "BASE_URL": "https://second.example/v1",
    "NAME": "Second"
  }
]
""",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert all(profile.id.startswith("env:") for profile in settings.llm_profiles)
    assert settings.default_llm_profile_id == settings.llm_profiles[0].id
    assert settings.llm_profiles[0].model == "first-model"
    assert settings.llm_profiles[1].api_key == "second-key"


def test_env_profile_id_does_not_change_with_display_name():
    config = {"MODEL": "same-model", "API_KEY": "key", "BASE_URL": "https://same.example/v1"}
    first = Settings(
        _env_file=None, secret_key="test", llm_models=json.dumps([{**config, "NAME": "A"}])
    )
    second = Settings(
        _env_file=None, secret_key="test", llm_models=json.dumps([{**config, "NAME": "B"}])
    )

    assert first.llm_profiles[0].id == second.llm_profiles[0].id


def test_single_line_llm_models_still_load_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODELS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'LLM_MODELS=[{"id":"single","name":"Single","api_key":"key",'
        '"base_url":"https://single.example/v1","model":"single-model"}]\n',
        encoding="utf-8",
    )

    assert Settings(_env_file=env_file).llm_profiles[0].id == "single"


def test_environment_llm_models_override_multiline_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LLM_MODELS",
        json.dumps(
            [
                {
                    "id": "override",
                    "name": "Override",
                    "api_key": "override-key",
                    "base_url": "https://override.example/v1",
                    "model": "override-model",
                }
            ]
        ),
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        """LLM_MODELS=[
  {"id":"file","name":"File","api_key":"file-key","
  "base_url":"https://file.example/v1","model":"file-model"}
]
""",
        encoding="utf-8",
    )

    assert Settings(_env_file=env_file).llm_profiles[0].id == "override"


def test_invalid_multiline_llm_models_still_report_json_error(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODELS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('LLM_MODELS=[\n  {"id": "broken",}\n]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="LLM_MODELS 必须是合法的 JSON 数组"):
        Settings(_env_file=env_file).llm_profiles


def test_explicit_none_disables_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODELS", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text('LLM_MODELS=[{"id":"file"}]\n', encoding="utf-8")

    assert Settings(_env_file=None).llm_models == ""


def test_legacy_default_model_id_resolves_to_configured_default(monkeypatch):
    settings = Settings(
        _env_file=None,
        secret_key="test-secret",
        llm_models=json.dumps(
            [
                {
                    "id": model_id,
                    "name": model_id,
                    "api_key": "test-key",
                    "base_url": "https://example.test/v1",
                    "model": model_id,
                }
                for model_id in ("first", "second")
            ]
        ),
        llm_default_model_id="second",
    )
    monkeypatch.setattr(ai_client, "settings", settings)

    assert ai_client.resolve_model_id("default") == "second"
    assert ai_client.resolve_model_id("first") == "first"
    with pytest.raises(ValueError, match="未知的 LLM 配置"):
        ai_client.resolve_model_id("unknown")


def test_recommend_topics_accepts_legacy_default_model_id(client, monkeypatch):
    settings = Settings(
        _env_file=None,
        secret_key="test-secret",
        llm_models=json.dumps(
            [
                {
                    "id": "current",
                    "name": "Current",
                    "api_key": "test-key",
                    "base_url": "https://example.test/v1",
                    "model": "current-model",
                }
            ]
        ),
    )
    monkeypatch.setattr(ai_client, "settings", settings)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"recommendations": []}'))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
    )
    monkeypatch.setattr("routers.topics.get_ai_client", lambda _: fake_client)

    result = client.get("/api/topics/recommend", params={"model": "default"})

    assert result.status_code == 200
    assert result.json() == {"recommendations": []}
