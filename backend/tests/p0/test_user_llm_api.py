import pytest

from core.config import settings
from core.ai_client import resolve_llm_profile, resolve_model_id
from models import UserLLMProfile


def model_payload(name: str = "我的模型"):
    return {
        "name": name,
        "api_key": "user-secret-key",
        "base_url": "https://custom.example/v1",
        "model": "custom-model",
    }


def test_custom_model_coexists_with_env_model_and_hides_api_key(client, db_session):
    environment_models = client.get("/api/llm/models").json()["models"]
    assert [model["id"] for model in environment_models] == [
        profile.id for profile in settings.llm_profiles
    ]
    assert all(model["source"] == "environment" for model in environment_models)
    assert all("api_key" not in model and "base_url" not in model for model in environment_models)
    response = client.post("/api/llm/models", json=model_payload())

    assert response.status_code == 201
    created = response.json()
    assert created["id"].startswith("custom:")
    assert created["source"] == "custom"
    assert "config_id" not in created
    assert "api_key" not in created
    assert "api_key_encrypted" not in created

    listed = client.get("/api/llm/models")
    assert listed.status_code == 200
    models = listed.json()["models"]
    assert len(models) == len(environment_models) + 1
    assert models[-1]["id"] == created["id"]
    assert models[-1]["source"] == "custom"
    assert all("api_key" not in model for model in models)

    record = db_session.query(UserLLMProfile).one()
    assert record.api_key_encrypted != "user-secret-key"
    assert resolve_llm_profile(created["id"]).api_key == "user-secret-key"
    with pytest.raises(ValueError, match="未知的 LLM 配置"):
        resolve_model_id(created["id"], user_id=999999)


def test_custom_models_can_share_the_same_official_model(client):
    first = client.post("/api/llm/models", json=model_payload("工作模型"))
    second = client.post("/api/llm/models", json=model_payload("个人模型"))

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(client.get("/api/llm/models").json()["models"]) == len(settings.llm_profiles) + 2


def test_custom_model_update_preserves_key_when_omitted(client, db_session):
    created = client.post("/api/llm/models", json=model_payload("saved-key")).json()

    response = client.put(
        f"/api/llm/models/{created['id']}",
        json={
            "name": "更新后的模型",
            "base_url": "https://updated.example/v1",
            "model": "updated-model",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "更新后的模型"
    assert resolve_llm_profile(created["id"]).api_key == "user-secret-key"


def test_custom_model_delete_removes_runtime_profile(client):
    created = client.post("/api/llm/models", json=model_payload("to-delete")).json()
    assert client.delete(f"/api/llm/models/{created['id']}").status_code == 200

    assert all(
        model["source"] == "environment" for model in client.get("/api/llm/models").json()["models"]
    )
    assert (
        client.put(
            f"/api/llm/models/{created['id']}",
            json={
                "name": "Deleted",
                "base_url": "https://deleted.example/v1",
                "model": "deleted-model",
            },
        ).status_code
        == 404
    )


def test_legacy_vision_settings_are_optional_and_roundtrip(client, db_session):
    automatic = client.post("/api/llm/models", json={**model_payload(), "image_input": "supported"})
    assert automatic.status_code == 201
    assert automatic.json()["max_images"] == 9
    assert resolve_llm_profile(automatic.json()["id"]).vision_token_budget is None
    fields = {
        "image_input": "supported",
        "vision_token_budget": 2048,
        "max_images": 3,
        "max_image_bytes": 1048576,
    }
    response = client.post("/api/llm/models", json={**model_payload(), **fields})
    assert response.status_code == 201
    model_id = response.json()["id"]
    assert {key: response.json()[key] for key in fields} == fields
    assert resolve_llm_profile(model_id).vision_token_budget == 2048
    listed = next(
        model for model in client.get("/api/llm/models").json()["models"] if model["id"] == model_id
    )
    assert {key: listed[key] for key in fields} == fields
    response = client.put(
        f"/api/llm/models/{model_id}",
        json={**model_payload(), **fields, "image_input": "unsupported"},
    )
    assert response.status_code == 200
    assert resolve_llm_profile(model_id).image_input == "unsupported"
