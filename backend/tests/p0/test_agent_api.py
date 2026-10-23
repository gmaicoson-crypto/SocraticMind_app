from services.agent.structured_ai import StructuredResult
from schemas.structured_ai import DiagnosticQuestions, DiagnosticScore, PersonalizedGraphDraft
from models import ChatMessage
from routers.agent import get_agent_generator


def fake_generator(schema, _messages, _context):
    if schema is DiagnosticQuestions:
        value = schema.model_validate(
            {
                "questions": [
                    {"question_id": "q1", "dimension": "prior_knowledge", "prompt": "Prior?"},
                    {"question_id": "q2", "dimension": "application", "prompt": "Apply?"},
                    {"question_id": "q3", "dimension": "limits", "prompt": "Limits?"},
                ]
            }
        )
    elif schema is DiagnosticScore:
        value = schema.model_validate(
            {
                "score": 65,
                "level": "foundation",
                "domain": "mathematics",
                "outcome_type": "concept",
                "strengths": [],
                "weaknesses": ["proof"],
                "graph_guidance": [],
            }
        )
    else:
        value = PersonalizedGraphDraft.model_validate(
            {
                "emoji": "📐",
                "nodes": [
                    {"key": "root", "label": "Root", "parent_keys": [], "estimated_minutes": 20},
                    {"key": "a", "label": "A", "parent_keys": ["root"], "estimated_minutes": 20},
                    {"key": "b", "label": "B", "parent_keys": ["root"], "estimated_minutes": 20},
                    {"key": "c", "label": "C", "parent_keys": ["a"], "estimated_minutes": 20},
                    {"key": "d", "label": "D", "parent_keys": ["a"], "estimated_minutes": 20},
                    {"key": "e", "label": "E", "parent_keys": ["b"], "estimated_minutes": 20},
                ],
            }
        )
    return StructuredResult(value=value, token_usage=3, latency_ms=1, attempts=1)


def onboarding_payload(use_diagnostic=False):
    return {
        "topic": "Linear algebra",
        "goal": "Understand vectors",
        "domain": "mathematics",
        "outcome_type": "concept",
        "familiarity": "beginner",
        "daily_minutes": 30,
        "timezone": "UTC",
        "use_diagnostic": use_diagnostic,
        "session_id": "api-session",
    }


def test_onboarding_api_exposes_recoverable_run_protocol(app, client, db_session):
    app.dependency_overrides[get_agent_generator] = lambda: fake_generator

    started = client.post("/api/agent/onboarding", json=onboarding_payload(True))
    assert started.status_code == 201
    body = started.json()
    assert body["status"] == "diagnosing"
    assert body["step"]["current"] == 1
    run_id = body["run_id"]

    restored = client.get(f"/api/agent/runs/{run_id}")
    assert restored.json() == body

    for number in range(1, 4):
        current = client.get(f"/api/agent/runs/{run_id}").json()
        answer = client.post(
            f"/api/agent/runs/{run_id}/answers",
            json={
                "step_id": current["step"]["step_id"],
                "version": current["version"],
                "answer": f"answer {number}",
            },
        )
        assert answer.status_code == 200
    assert answer.json()["status"] == "awaiting_confirmation"
    assert answer.json()["preview"]["total_minutes"] == 120
    assert answer.json()["preview"]["daily_minutes"] == 30

    confirmed = client.post(f"/api/agent/runs/{run_id}/confirm", json={"request_id": "api-confirm"})
    assert confirmed.status_code == 200
    assert confirmed.json()["result"]["topic_id"] > 0
    repeated = client.post(f"/api/agent/runs/{run_id}/confirm", json={"request_id": "api-confirm"})
    assert repeated.json() == confirmed.json()
    messages = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.session_id == "api-session")
        .order_by(ChatMessage.id)
        .all()
    )
    assert [message.message_type for message in messages] == [
        "agent_step",
        "agent_answer",
        "agent_step",
        "agent_answer",
        "agent_step",
        "agent_answer",
        "plan_preview",
        "agent_result",
    ]
    assert messages[0].metadata_json["step"]["current"] == 1
    assert messages[-1].metadata_json["result"] == confirmed.json()["result"]


def test_patch_regenerates_preview_and_cancel_is_terminal(app, client):
    app.dependency_overrides[get_agent_generator] = lambda: fake_generator
    run = client.post("/api/agent/onboarding", json=onboarding_payload()).json()

    patched = client.patch(
        f"/api/agent/runs/{run['run_id']}",
        json={"daily_minutes": 10, "goal": "A revised goal"},
    )
    assert patched.status_code == 200
    assert patched.json()["preview"]["goal"] == "A revised goal"
    assert len(patched.json()["preview"]["plan_items"]) == 12

    cancelled = client.post(f"/api/agent/runs/{run['run_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    retry = client.post(f"/api/agent/runs/{run['run_id']}/retry")
    assert retry.status_code == 409
    assert retry.json()["code"] == "AGENT_RETRY_NOT_ALLOWED"


def test_onboarding_validation_rejects_out_of_range_daily_minutes(client):
    payload = onboarding_payload()
    payload["daily_minutes"] = 241
    response = client.post("/api/agent/onboarding", json=payload)
    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "请求参数校验失败",
        "retryable": False,
    }
