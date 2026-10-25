"""Mobile recovery must not repeat model work or confirm an unseen preview."""

from uuid import uuid4

import pytest

from core.deps import get_current_user
from models import AgentRun, StudyPlan, Topic, User
from routers.agent import get_agent_generator
from services.agent.structured_ai import StructuredAIError
from tests.p0.test_agent_api import fake_generator, onboarding_payload


@pytest.fixture()
def generator(app):
    calls = []

    def generate(*arguments):
        calls.append(arguments)
        return fake_generator(*arguments)

    app.dependency_overrides[get_agent_generator] = lambda: generate
    return calls


def start(client, *, diagnostic=False):
    payload = {**onboarding_payload(diagnostic), "run_id": str(uuid4())}
    response = client.post("/api/agent/onboarding", json=payload)
    assert response.status_code == 201
    return payload, response.json()


def test_lost_creation_response_replays_current_run_without_model_call(
    client, generator, db_session
):
    payload, run = start(client)
    assert run["run_id"] == payload["run_id"]
    assert run["processing"] is False
    assert run["input"]["goal"] == payload["goal"]
    assert not {"model", "session_id", "run_id"} & run["input"].keys()
    repeat = client.post("/api/agent/onboarding", json=payload)
    assert repeat.status_code == 201
    assert repeat.json() == run == client.get(f"/api/agent/runs/{run['run_id']}").json()
    assert len(generator) == 1
    assert db_session.query(AgentRun).count() == 1
    assert db_session.query(Topic).count() == 0

    edited = client.patch(
        f"/api/agent/runs/{run['run_id']}",
        json={"version": run["version"], "daily_minutes": 20, "goal": "Revised"},
    )
    assert edited.status_code == 200
    assert edited.json()["input"]["goal"] == "Revised"
    assert client.post("/api/agent/onboarding", json=payload).json() == edited.json()
    assert len(generator) == 2


def test_reused_creation_id_with_different_input_is_rejected(client, generator):
    payload, run = start(client)
    response = client.post("/api/agent/onboarding", json={**payload, "goal": "Different"})
    assert response.status_code == 409
    assert response.json()["code"] == "AGENT_REQUEST_CONFLICT"
    assert client.get(f"/api/agent/runs/{run['run_id']}").json() == run
    assert len(generator) == 1


def test_replay_is_account_scoped(app, client, generator, db_session):
    payload, run = start(client)
    other = User(username="other", email="other@example.test", hashed_password="synthetic")
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    for response in [
        client.post("/api/agent/onboarding", json=payload),
        client.get(f"/api/agent/runs/{run['run_id']}"),
        client.post(f"/api/agent/runs/{run['run_id']}/cancel"),
    ]:
        assert response.status_code == 404
        assert response.json()["code"] == "RUN_NOT_FOUND"
    assert len(generator) == 1


def test_stale_edit_and_confirmation_cannot_apply_unseen_preview(client, generator, db_session):
    _, run = start(client)
    path = f"/api/agent/runs/{run['run_id']}"
    updated = client.patch(path, json={"version": run["version"], "daily_minutes": 10}).json()
    for response in [
        client.patch(path, json={"version": run["version"], "goal": "Stale"}),
        client.post(path + "/confirm", json={"version": run["version"], "request_id": "confirm"}),
    ]:
        assert response.status_code == 409
        assert response.json()["code"] == "AGENT_STATE_CONFLICT"
    assert db_session.query(Topic).count() == 0
    assert len(generator) == 2
    confirm = {"version": updated["version"], "request_id": "confirm"}
    completed = client.post(path + "/confirm", json=confirm)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert client.post(path + "/confirm", json=confirm).json() == completed.json()
    assert db_session.query(Topic).count() == db_session.query(StudyPlan).count() == 1


def test_cancel_is_replayable_and_creation_does_not_restart_it(client, generator):
    payload, run = start(client, diagnostic=True)
    path = f"/api/agent/runs/{run['run_id']}"
    cancelled = client.post(path + "/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["processing"] is False
    assert client.post(path + "/cancel").json() == cancelled
    assert client.post("/api/agent/onboarding", json=payload).json() == cancelled
    assert client.post(path + "/retry", json={"version": cancelled["version"]}).status_code == 409
    assert len(generator) == 1


def test_failed_start_replay_is_read_only_and_retry_checks_version(app, client):
    calls = []

    def unavailable(*_arguments):
        calls.append(1)
        raise StructuredAIError("AI_TIMEOUT", "synthetic timeout", retryable=True)

    app.dependency_overrides[get_agent_generator] = lambda: unavailable
    payload, run = start(client)
    path = f"/api/agent/runs/{run['run_id']}"
    assert run["status"] == "failed"
    assert run["processing"] is False
    assert client.post("/api/agent/onboarding", json=payload).json() == run
    assert len(calls) == 1
    stale = client.post(path + "/retry", json={"version": run["version"] - 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "AGENT_STATE_CONFLICT"
    retried = client.post(path + "/retry", json={"version": run["version"]}).json()
    assert retried["status"] == "failed"
    assert retried["version"] > run["version"]
    assert client.post(path + "/retry", json={"version": run["version"]}).status_code == 409
    assert len(calls) == 2
    app.dependency_overrides[get_agent_generator] = lambda: fake_generator
    assert client.post(path + "/retry").json()["status"] == "awaiting_confirmation"


@pytest.mark.parametrize("value", ["invalid", "00000000-0000-0000-0000-000000000000", 42])
def test_creation_identifier_requires_v4_uuid(client, value):
    response = client.post("/api/agent/onboarding", json={**onboarding_payload(), "run_id": value})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"version": 1},
        {"goal": None},
        {"daily_minutes": None},
        {"timezone": None},
        {"version": True, "goal": "New"},
        {"version": 1.0, "goal": "New"},
        {"version": "1", "goal": "New"},
        {"version": -1, "goal": "New"},
    ],
)
def test_invalid_edit_is_rejected_before_model_call(client, generator, patch):
    _, run = start(client)
    response = client.patch(f"/api/agent/runs/{run['run_id']}", json=patch)
    assert response.status_code == 422
    assert len(generator) == 1


def test_target_date_can_be_explicitly_cleared_and_legacy_creation_is_preserved(client, generator):
    payload = {**onboarding_payload(), "target_date": "2027-01-01"}
    first = client.post("/api/agent/onboarding", json=payload).json()
    second = client.post("/api/agent/onboarding", json=payload).json()
    assert first["run_id"] != second["run_id"]
    cleared = client.patch(f"/api/agent/runs/{first['run_id']}", json={"target_date": None})
    assert cleared.status_code == 200
    assert cleared.json()["input"]["target_date"] is None
    assert cleared.json()["preview"]["target_date"] is None


@pytest.mark.parametrize("field", ["goal", "daily_minutes", "timezone"])
def test_legacy_invalid_input_does_not_block_read_or_cancel(client, generator, db_session, field):
    _, run = start(client)
    stored = db_session.get(AgentRun, run["run_id"])
    stored.state_json = {
        **stored.state_json,
        "params": {**stored.state_json["params"], field: None},
    }
    db_session.commit()
    path = f"/api/agent/runs/{run['run_id']}"
    restored = client.get(path)
    assert restored.status_code == 200
    assert restored.json()["input"] is None
    assert restored.json()["preview"] == run["preview"]
    assert restored.json()["status"] == run["status"]
    cancelled = client.post(path + "/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["input"] is None
    assert client.post(path + "/cancel").json() == cancelled.json()
    assert len(generator) == 1
