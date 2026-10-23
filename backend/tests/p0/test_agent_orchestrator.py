import pytest

from core.errors import ApiError
from models import AgentRun, LearnerMemory, Node, StudyPlan, Topic
from schemas.agent import OnboardingRequest
from schemas.structured_ai import (
    DiagnosticQuestions,
    DiagnosticScore,
    PersonalizedGraphDraft,
)
from services.agent.orchestrator import (
    cancel_run,
    confirm_run,
    get_run,
    retry_run,
    start_onboarding,
    submit_answer,
)
from services.agent.structured_ai import StructuredAIError, StructuredResult


def onboarding_request(use_diagnostic=True):
    return OnboardingRequest(
        topic="Linear algebra",
        goal="Understand vectors",
        domain="mathematics",
        outcome_type="concept",
        familiarity="beginner",
        daily_minutes=30,
        timezone="UTC",
        use_diagnostic=use_diagnostic,
        session_id="session-1",
    )


def graph_payload():
    return {
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


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def __call__(self, schema, messages, context):
        self.calls.append((schema, messages, context))
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
                    "score": 70,
                    "level": "foundation",
                    "domain": "mathematics",
                    "outcome_type": "concept",
                    "strengths": ["Vectors"],
                    "weaknesses": ["Proofs"],
                    "graph_guidance": ["Emphasize proofs"],
                }
            )
        elif schema is PersonalizedGraphDraft:
            value = schema.model_validate(graph_payload())
        else:
            raise AssertionError(f"Unexpected schema: {schema}")
        return StructuredResult(value=value, token_usage=10, latency_ms=5, attempts=1)


def answer_current(db_session, user_id, run, answer, generator):
    state = run.state_json
    return submit_answer(
        db_session,
        user_id=user_id,
        run_id=run.id,
        step_id=state["step_id"],
        version=run.version,
        answer=answer,
        generator=generator,
    )


def test_diagnostic_run_recovers_steps_rejects_stale_and_builds_preview(db_session, auth_user):
    generator = FakeGenerator()
    run = start_onboarding(
        db_session, user_id=auth_user.id, request=onboarding_request(), generator=generator
    )

    assert run.status == "diagnosing"
    assert run.state_json["step_id"] == "diagnostic-question-1"
    restored = get_run(db_session, user_id=auth_user.id, run_id=run.id)
    assert restored.version == run.version
    assert len(generator.calls) == 1

    run = answer_current(db_session, auth_user.id, run, "answer 1", generator)
    assert run.state_json["step_id"] == "diagnostic-question-2"
    with pytest.raises(ApiError) as stale:
        submit_answer(
            db_session,
            user_id=auth_user.id,
            run_id=run.id,
            step_id="diagnostic-question-1",
            version=run.version - 1,
            answer="duplicate",
            generator=generator,
        )
    assert stale.value.code == "AGENT_STATE_CONFLICT"

    run = answer_current(db_session, auth_user.id, run, "answer 2", generator)
    run = answer_current(db_session, auth_user.id, run, "answer 3", generator)
    assert run.status == "awaiting_confirmation"
    assert len(run.state_json["preview"]["nodes"]) == 6
    assert run.state_json["diagnostic_result"]["score"] == 70
    assert [call[0] for call in generator.calls] == [
        DiagnosticQuestions,
        DiagnosticScore,
        PersonalizedGraphDraft,
    ]


def test_skip_diagnostic_confirms_atomically_and_is_idempotent(db_session, auth_user):
    generator = FakeGenerator()
    run = start_onboarding(
        db_session,
        user_id=auth_user.id,
        request=onboarding_request(use_diagnostic=False),
        generator=generator,
    )
    assert run.status == "awaiting_confirmation"
    assert [call[0] for call in generator.calls] == [PersonalizedGraphDraft]

    first = confirm_run(db_session, user_id=auth_user.id, run_id=run.id, request_id="confirm-1")
    second = confirm_run(db_session, user_id=auth_user.id, run_id=run.id, request_id="confirm-1")

    assert first.result_json == second.result_json
    assert db_session.query(Topic).count() == 1
    assert db_session.query(Node).count() == 6
    assert db_session.query(StudyPlan).count() == 1
    assert {memory.kind for memory in db_session.query(LearnerMemory).all()} == {
        "goal",
        "background",
    }


def test_diagnostic_memories_are_written_only_after_confirm(db_session, auth_user):
    generator = FakeGenerator()
    run = start_onboarding(
        db_session, user_id=auth_user.id, request=onboarding_request(), generator=generator
    )
    for index in range(3):
        run = answer_current(db_session, auth_user.id, run, f"answer {index}", generator)
    assert db_session.query(LearnerMemory).count() == 0

    run = confirm_run(
        db_session, user_id=auth_user.id, run_id=run.id, request_id="confirm-diagnostic"
    )
    assert run.status == "completed"
    assert {memory.kind for memory in db_session.query(LearnerMemory).all()} == {
        "goal",
        "background",
        "strength",
        "weakness",
    }


def test_cancelled_preview_creates_no_business_data(db_session, auth_user):
    run = start_onboarding(
        db_session,
        user_id=auth_user.id,
        request=onboarding_request(use_diagnostic=False),
        generator=FakeGenerator(),
    )
    cancelled = cancel_run(db_session, user_id=auth_user.id, run_id=run.id)
    assert cancelled.status == "cancelled"
    assert db_session.query(Topic).count() == 0
    assert db_session.query(StudyPlan).count() == 0


def test_retry_resumes_only_failed_model_stage(db_session, auth_user):
    good = FakeGenerator()
    calls = 0

    def flaky(schema, messages, context):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StructuredAIError("AI_TIMEOUT", "slow", retryable=True)
        return good(schema, messages, context)

    failed = start_onboarding(
        db_session, user_id=auth_user.id, request=onboarding_request(), generator=flaky
    )
    assert failed.status == "failed"
    assert failed.error_code == "AI_TIMEOUT"

    recovered = retry_run(db_session, user_id=auth_user.id, run_id=failed.id, generator=flaky)
    assert recovered.status == "diagnosing"
    assert recovered.state_json["step_id"] == "diagnostic-question-1"
    assert calls == 2


def test_model_calls_hold_no_transaction_and_graph_retry_does_not_rescore(db_session, auth_user):
    good = FakeGenerator()
    called_schemas = []
    graph_failed = False

    def fail_graph_once(schema, messages, context):
        nonlocal graph_failed
        assert db_session.in_transaction() is False
        called_schemas.append(schema)
        if schema is PersonalizedGraphDraft and not graph_failed:
            graph_failed = True
            raise StructuredAIError("AI_TIMEOUT", "slow", retryable=True)
        return good(schema, messages, context)

    run = start_onboarding(
        db_session,
        user_id=auth_user.id,
        request=onboarding_request(),
        generator=fail_graph_once,
    )
    for index in range(3):
        run = answer_current(db_session, auth_user.id, run, f"answer {index}", fail_graph_once)
    assert run.status == "failed"
    assert run.state_json["processing_stage"] == "graph_draft"

    run = retry_run(
        db_session,
        user_id=auth_user.id,
        run_id=run.id,
        generator=fail_graph_once,
    )
    assert run.status == "awaiting_confirmation"
    assert called_schemas.count(DiagnosticScore) == 1
    assert called_schemas.count(PersonalizedGraphDraft) == 2


def test_run_lookup_hides_other_users(db_session, auth_user):
    run = AgentRun(
        user_id=auth_user.id,
        run_type="onboarding",
        status="collecting",
        state_json={},
    )
    db_session.add(run)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        get_run(db_session, user_id=auth_user.id + 100, run_id=run.id)
    assert error.value.status_code == 404
