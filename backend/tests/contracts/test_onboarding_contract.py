"""Shared synthetic responses are produced by the real run service and HTTP projection."""

from datetime import date
import json
from pathlib import Path

import pytest

from models import AgentRun, AssessmentAttempt
from routers.agent import get_agent_generator, serialize_run
from services.agent import orchestrator
from services.agent.structured_ai import StructuredAIError
from tests.p0.test_agent_api import fake_generator
from tests.p0.test_assessment_service import AssessmentGenerator, create_assessable_node


ROOT = Path(__file__).resolve().parents[3]
DATA = json.loads((ROOT / "contracts/fixtures/onboarding-runs.json").read_text())


def test_shared_onboarding_steps_preview_edit_and_confirm(app, client, db_session, monkeypatch):
    monkeypatch.setattr(orchestrator, "today_in_timezone", lambda zone: (date(2026, 10, 25), zone))
    observed = []

    def generate(*arguments):
        if not observed:
            run = db_session.get(AgentRun, DATA["request"]["run_id"])
            observed.append(serialize_run(run).model_dump(mode="json"))
        return fake_generator(*arguments)

    app.dependency_overrides[get_agent_generator] = lambda: generate
    response = client.post("/api/agent/onboarding", json=DATA["request"])
    assert response.status_code == 201
    assert observed == [DATA["responses"]["processing"]]
    run = response.json()
    assert run == DATA["responses"]["diagnosing"]
    path = f"/api/agent/runs/{run['run_id']}"
    for answer in DATA["answers"]:
        response = client.post(
            path + "/answers",
            json={
                "step_id": run["step"]["step_id"],
                "version": run["version"],
                "answer": answer,
            },
        )
        assert response.status_code == 200
        run = response.json()
    assert run == DATA["responses"]["preview"]
    run = client.patch(path, json={"daily_minutes": 20, "version": run["version"]}).json()
    assert run == DATA["responses"]["edited"]
    response = client.post(
        path + "/confirm",
        json={
            "request_id": "fixture-confirm",
            "version": run["version"],
        },
    )
    assert response.json() == DATA["responses"]["completed"]
    assert client.get(path).json() == response.json()


def test_shared_failure_and_cancellation_are_recoverable(app, client):
    def generate(*_arguments):
        raise StructuredAIError("AI_TIMEOUT", "synthetic", retryable=True)

    app.dependency_overrides[get_agent_generator] = lambda: generate
    failed = client.post("/api/agent/onboarding", json=DATA["failed_request"])
    assert failed.status_code == 201
    assert failed.json() == DATA["responses"]["failed"]
    path = f"/api/agent/runs/{failed.json()['run_id']}"
    assert client.post(path + "/cancel").json() == DATA["responses"]["cancelled"]
    assert client.get(path).json() == DATA["responses"]["cancelled"]


def test_version_guard_and_cancel_replay_cover_shared_assessment_endpoint(
    app, client, db_session, auth_user
):
    node, _ = create_assessable_node(db_session, auth_user)

    def unavailable(*_arguments):
        raise StructuredAIError("AI_TIMEOUT", "synthetic", retryable=True)

    app.dependency_overrides[get_agent_generator] = lambda: unavailable
    failed = client.post(
        "/api/agent/assessments",
        json={
            "node_id": node.id,
            "request_id": "assessment-fixture",
        },
    ).json()
    assert failed["input"] is None
    path = f"/api/agent/runs/{failed['run_id']}"
    stale = client.post(path + "/retry", json={"version": failed["version"] - 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "AGENT_STATE_CONFLICT"
    app.dependency_overrides[get_agent_generator] = lambda: AssessmentGenerator()
    assert (
        client.post(path + "/retry", json={"version": failed["version"]}).json()["status"]
        == "assessing"
    )
    cancelled = client.post(path + "/cancel")
    assert cancelled.status_code == 200
    assert client.post(path + "/cancel").json() == cancelled.json()
    assert db_session.query(AssessmentAttempt).one().status == "cancelled"


@pytest.mark.parametrize("suffix,body", [("confirm", {"request_id": "confirm"}), ("retry", {})])
@pytest.mark.parametrize("version", [True, "1", 1.0, -1])
def test_version_wire_type_is_strict_on_shared_mutations(client, suffix, body, version):
    response = client.post(f"/api/agent/runs/synthetic/{suffix}", json={**body, "version": version})
    assert response.status_code == 422


def test_openapi_keeps_legacy_inputs_and_declares_mobile_recovery():
    schema = json.loads((ROOT / "contracts/openapi/socraticmind.json").read_text())
    shapes = schema["components"]["schemas"]
    assert "run_id" not in shapes["OnboardingRequest"]["required"]
    assert shapes["OnboardingRequest"]["properties"]["run_id"]["anyOf"][0]["format"] == "uuid4"
    assert "input" in shapes["AgentRunResponse"]["properties"]
    assert "processing" in shapes["AgentRunResponse"]["properties"]
    assert shapes["ConfirmRunRequest"]["required"] == ["request_id"]
    retry = schema["paths"]["/api/agent/runs/{run_id}/retry"]["post"]["requestBody"]
    assert not retry.get("required", False)
