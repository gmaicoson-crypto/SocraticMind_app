from datetime import date

import pytest

from core.errors import ApiError
from models import (
    AssessmentAttempt,
    LearnerMemory,
    Node,
    StudyPlan,
    StudyPlanItem,
    Topic,
)
from schemas.structured_ai import AssessmentQuestions, AssessmentScore
from services.assessments import (
    retry_assessment,
    start_assessment,
    submit_assessment_answer,
)
from services.agent.structured_ai import StructuredAIError, StructuredResult


class AssessmentGenerator:
    def __init__(self, *, score=10, confidence=0.8, critical=False):
        self.score = score
        self.confidence = confidence
        self.critical = critical
        self.calls = []

    def __call__(self, schema, _messages, _context):
        self.calls.append(schema)
        if schema is AssessmentQuestions:
            questions = []
            for index, dimension in enumerate(("concept", "application", "boundary"), 1):
                questions.append(
                    {
                        "question_id": f"aq{index}",
                        "dimension": dimension,
                        "prompt": f"Question {index}",
                        "rubric": [
                            {
                                "criterion": "Observable evidence",
                                "observable_standards": ["Specific and correct"],
                            }
                        ],
                    }
                )
            value = schema.model_validate({"questions": questions})
        else:
            parts = [self.score // 3] * 3
            for index in range(self.score % 3):
                parts[index] += 1
            value = AssessmentScore.model_validate(
                {
                    "scores": [
                        {
                            "question_id": f"aq{index}",
                            "score": part,
                            "rationale": "Evidence",
                        }
                        for index, part in enumerate(parts, 1)
                    ],
                    "total_score": self.score,
                    "evaluation_confidence": self.confidence,
                    "critical_misconception": self.critical,
                    "evidence": "Overall evidence",
                    "weaknesses": ["A weak point"] if self.score < 9 else [],
                }
            )
        return StructuredResult(value=value, token_usage=5, latency_ms=2, attempts=1)


def create_assessable_node(
    db_session, user, *, domain="education", outcome="concept", state="available"
):
    topic = Topic(user_id=user.id, title="Assessment topic")
    db_session.add(topic)
    db_session.flush()
    node = Node(
        topic_id=topic.id,
        node_key="root",
        label="Root",
        state=state,
        estimated_minutes=30,
    )
    db_session.add(node)
    db_session.flush()
    plan = StudyPlan(
        user_id=user.id,
        topic_id=topic.id,
        goal="Learn",
        domain=domain,
        outcome_type=outcome,
        daily_minutes=30,
        timezone="UTC",
        start_date=date(2026, 9, 7),
        estimated_end_date=date(2026, 9, 7),
        status="active",
    )
    db_session.add(plan)
    db_session.flush()
    item = StudyPlanItem(
        plan_id=plan.id,
        node_id=node.id,
        scheduled_date=date(2026, 9, 7),
        day_order=1,
        estimated_minutes=30,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()
    return node, item


def complete_answers(db_session, user_id, run, generator):
    for index in range(3):
        state = run.state_json
        run = submit_assessment_answer(
            db_session,
            user_id=user_id,
            run_id=run.id,
            step_id=state["step_id"],
            version=run.version,
            answer=f"answer {index}",
            generator=generator,
        )
    return run


def test_passing_assessment_records_evidence_and_mastery(db_session, auth_user):
    node, item = create_assessable_node(db_session, auth_user)
    generator = AssessmentGenerator(score=10, confidence=0.82)
    run = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="start-pass",
        generator=generator,
    )
    assert run.status == "assessing"
    assert run.state_json["step_id"] == "assessment-question-1"

    run = complete_answers(db_session, auth_user.id, run, generator)
    db_session.refresh(node)
    db_session.refresh(item)
    assert run.status == "completed"
    assert run.result_json["passed"] is True
    assert run.result_json["total_score"] == 10
    assert node.state == "mastered"
    assert node.mastery_source == "assessment"
    assert item.status == "completed"
    memory = db_session.query(LearnerMemory).one()
    assert memory.topic_id == node.topic_id
    assert memory.kind == "strength"
    assert memory.source == "assessment"
    assert memory.confidence == pytest.approx(0.82)


@pytest.mark.parametrize(
    ("score", "confidence", "critical"),
    [(8, 0.9, False), (10, 0.6, False), (10, 0.9, True)],
)
def test_deterministic_gate_keeps_failed_assessment_available(
    db_session, auth_user, score, confidence, critical
):
    node, _item = create_assessable_node(db_session, auth_user)
    generator = AssessmentGenerator(score=score, confidence=confidence, critical=critical)
    run = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id=f"start-{score}-{confidence}-{critical}",
        generator=generator,
    )
    run = complete_answers(db_session, auth_user.id, run, generator)
    db_session.refresh(node)
    assert run.result_json["passed"] is False
    assert node.state == "available"
    memory = db_session.query(LearnerMemory).one()
    assert memory.topic_id == node.topic_id
    assert memory.kind == "weakness"
    assert memory.source == "assessment"
    expected = "A weak point" if score < 9 else "“Root”的评估尚未通过"
    assert memory.content == expected


def test_high_risk_practical_assessment_never_auto_masters(db_session, auth_user):
    node, _item = create_assessable_node(
        db_session, auth_user, domain="medical", outcome="procedure"
    )
    generator = AssessmentGenerator(score=12, confidence=0.95)
    run = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="high-risk",
        generator=generator,
    )
    run = complete_answers(db_session, auth_user.id, run, generator)
    db_session.refresh(node)
    assert run.result_json["passed"] is False
    assert run.result_json["professional_review_required"] is True
    assert node.state == "available"


def test_locked_node_is_rejected(db_session, auth_user):
    locked, _item = create_assessable_node(db_session, auth_user, state="locked")
    with pytest.raises(ApiError) as error:
        start_assessment(
            db_session,
            user_id=auth_user.id,
            node_id=locked.id,
            request_id="locked",
            generator=AssessmentGenerator(),
        )
    assert error.value.code == "NODE_LOCKED"


def test_active_attempt_and_completed_result_are_reused(db_session, auth_user):
    node, _item = create_assessable_node(db_session, auth_user)
    generator = AssessmentGenerator()
    active = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="active-one",
        generator=generator,
    )
    resumed = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="active-two",
        generator=generator,
    )
    assert resumed.id == active.id
    assert generator.calls.count(AssessmentQuestions) == 1

    completed = complete_answers(db_session, auth_user.id, resumed, generator)
    existing = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="after-complete",
        generator=generator,
    )
    assert existing.id == completed.id


def test_failed_question_generation_can_retry(db_session, auth_user):
    node, _item = create_assessable_node(db_session, auth_user)
    good = AssessmentGenerator()
    calls = 0

    def flaky(schema, messages, context):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StructuredAIError("AI_TIMEOUT", "slow", retryable=True)
        return good(schema, messages, context)

    failed = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="retry-start",
        generator=flaky,
    )
    assert failed.status == "failed"
    recovered = retry_assessment(
        db_session, user_id=auth_user.id, run_id=failed.id, generator=flaky
    )
    assert recovered.status == "assessing"
    assert recovered.state_json["step_id"] == "assessment-question-1"


def test_invalid_score_question_ids_fail_before_recording_evidence(db_session, auth_user):
    node, _item = create_assessable_node(db_session, auth_user)
    good = AssessmentGenerator(score=10, confidence=0.8)

    def invalid_score(schema, messages, context):
        result = good(schema, messages, context)
        if schema is AssessmentScore:
            result.value.scores[0].question_id = "unknown-question"
        return result

    run = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=node.id,
        request_id="invalid-score-ids",
        generator=invalid_score,
    )
    run = complete_answers(db_session, auth_user.id, run, invalid_score)

    assert run.status == "failed"
    assert run.error_code == "ASSESSMENT_SCORE_INVALID"
    assert run.retryable is True
    attempt = db_session.query(AssessmentAttempt).filter_by(run_id=run.id).one()
    assert attempt.status == "failed"
    assert db_session.query(LearnerMemory).count() == 0
