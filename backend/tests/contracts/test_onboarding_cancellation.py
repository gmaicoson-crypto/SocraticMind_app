"""A lost create may arrive after cancellation; the terminal reservation must survive."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy.exc import IntegrityError

from core.deps import get_current_user
from models import AgentRun, StudyPlan, Topic, User
from routers import agent
from services.agent.onboarding_creation import cancel_onboarding
from tests.p0.test_agent_api import fake_generator, onboarding_payload


ROOT = Path(__file__).resolve().parents[3]
DATA = json.loads((ROOT / "contracts/fixtures/onboarding-cancellation.json").read_text())


def test_cancellation_contract_declares_uuid4_without_model_or_body():
    schema = json.loads((ROOT / "contracts/openapi/socraticmind.json").read_text())
    endpoint = schema["paths"]["/api/agent/onboarding/{run_id}/cancel"]["post"]
    assert "requestBody" not in endpoint
    identifier = next(item for item in endpoint["parameters"] if item["name"] == "run_id")
    assert identifier["required"] and identifier["schema"]["format"] == "uuid4"
    assert "200" in endpoint["responses"]


def test_cancel_before_create_survives_lost_response_and_late_changed_payload(
    app, client, db_session, monkeypatch
):
    run_id = DATA["run_id"]
    cancel = f"/api/agent/onboarding/{run_id}/cancel"
    path = f"/api/agent/runs/{run_id}"

    def forbidden(*_args, **_kwargs):
        pytest.fail("Cancellation/reservation replay must not invoke model configuration or AI")

    with monkeypatch.context() as patch:
        patch.setattr(agent, "load_user_profiles", forbidden)
        patch.setattr(agent, "selected_model", forbidden)
        first = client.post(cancel)
        assert first.status_code == 200
        assert first.json() == DATA["response"]
        assert client.post(cancel).json() == first.json()
    assert client.get(path).json() == first.json()
    app.dependency_overrides[agent.get_agent_generator] = lambda: forbidden
    for diagnostic, goal in [(False, "first goal"), (True, "changed after response loss")]:
        response = client.post(
            "/api/agent/onboarding",
            json={**onboarding_payload(diagnostic), "run_id": run_id, "goal": goal},
        )
        assert response.status_code == 201
        assert response.json() == first.json()
    assert client.post(path + "/cancel").json() == first.json()
    for suffix, body in [("retry", {"version": 1}), ("confirm", {"version": 1, "request_id": "r"})]:
        assert client.post(path + "/" + suffix, json=body).status_code == 409
    record = db_session.get(AgentRun, run_id)
    assert record.state_json == {"creation_cancelled": True, "processing": False}
    assert record.model is None and record.session_id is None
    assert db_session.query(AgentRun).count() == 1
    assert db_session.query(Topic).count() == db_session.query(StudyPlan).count() == 0


def test_existing_run_cancel_preserves_fingerprint_and_completed_result(app, client, db_session):
    app.dependency_overrides[agent.get_agent_generator] = lambda: fake_generator
    payload = {**onboarding_payload(), "run_id": str(uuid4())}
    created = client.post("/api/agent/onboarding", json=payload).json()
    cancel = f"/api/agent/onboarding/{created['run_id']}/cancel"
    result = client.post(cancel)
    assert result.status_code == 200 and result.json()["status"] == "cancelled"
    assert result.json()["version"] == created["version"] + 1
    assert client.post(cancel).json() == result.json()
    assert client.post("/api/agent/onboarding", json=payload).json() == result.json()
    changed = client.post("/api/agent/onboarding", json={**payload, "goal": "different"})
    assert changed.status_code == 409 and changed.json()["code"] == "AGENT_REQUEST_CONFLICT"
    payload["run_id"] = str(uuid4())
    created = client.post("/api/agent/onboarding", json=payload).json()
    path = f"/api/agent/runs/{created['run_id']}"
    completed = client.post(path + "/confirm", json={"request_id": "done"}).json()
    response = client.post(f"/api/agent/onboarding/{created['run_id']}/cancel")
    assert response.status_code == 409
    assert client.get(path).json() == completed
    assert db_session.query(Topic).count() == db_session.query(StudyPlan).count() == 1


@pytest.mark.parametrize("kind", ["onboarding", "assessment", "topic_plan"])
def test_other_account_or_flow_cannot_be_cancelled_or_claimed(
    app, client, db_session, auth_user, kind
):
    other = User(username="other", email="cancel-other@example.test", hashed_password="synthetic")
    db_session.add(other)
    db_session.commit()
    run_id = str(uuid4())
    owner = other.id if kind == "onboarding" else auth_user.id
    record = AgentRun(id=run_id, user_id=owner, run_type=kind, status="collecting", version=4)
    db_session.add(record)
    db_session.commit()
    response = client.post(f"/api/agent/onboarding/{run_id}/cancel")
    assert response.status_code == 404 and response.json()["code"] == "RUN_NOT_FOUND"
    db_session.refresh(record)
    assert record.status == "collecting" and record.version == 4
    response = client.post("/api/agent/onboarding", json={**onboarding_payload(), "run_id": run_id})
    assert response.status_code == 404
    assert db_session.query(AgentRun).count() == 1


@pytest.mark.parametrize("run_id", ["invalid", "00000000-0000-0000-0000-000000000000"])
def test_cancel_requires_uuid4_and_does_not_allocate_invalid_ids(client, db_session, run_id):
    assert client.post(f"/api/agent/onboarding/{run_id}/cancel").status_code == 422
    assert db_session.query(AgentRun).count() == 0


def test_unauthenticated_cancel_does_not_allocate_a_record(app, client, db_session):
    def unauthenticated():
        raise HTTPException(status_code=401)

    app.dependency_overrides[get_current_user] = unauthenticated
    assert client.post(f"/api/agent/onboarding/{uuid4()}/cancel").status_code == 401
    assert db_session.query(AgentRun).count() == 0


def test_unrelated_insert_integrity_error_is_not_reported_as_cancellation(
    db_session, auth_user, monkeypatch
):
    def invalid_commit():
        raise IntegrityError("synthetic insert", {}, Exception("unrelated constraint"))

    monkeypatch.setattr(db_session, "commit", invalid_commit)
    with pytest.raises(IntegrityError):
        cancel_onboarding(db_session, user_id=auth_user.id, run_id=str(uuid4()))
    assert db_session.query(AgentRun).count() == 0
