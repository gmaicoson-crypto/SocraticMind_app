import json
from copy import deepcopy

from sqlalchemy.orm import Session

from core.ai_client import resolve_model_id
from core.errors import ApiError
from models import AgentRun, AssessmentAttempt, Node, StudyPlan, Topic
from models.enums import AgentRunStatus, AgentRunType, AssessmentStatus, MasterySource
from schemas.structured_ai import AssessmentQuestions, AssessmentScore
from services.agent.orchestrator import Generator, _invoke
from services.agent.run_store import RunSnapshot, _load_owned, _snapshot, require_version
from services.agent.state_machine import transition
from services.agent.structured_ai import StructuredAIError, high_risk_notice
from services.mastery import record_mastery
from services.memories import upsert_assessment_memories


def _owned_node(db: Session, user_id: int, node_id: int) -> Node:
    node = (
        db.query(Node)
        .join(Topic, Node.topic_id == Topic.id)
        .filter(Node.id == node_id, Topic.user_id == user_id)
        .with_for_update()
        .first()
    )
    if node is None:
        raise ApiError(status_code=404, code="NODE_NOT_FOUND", message="节点不存在")
    return node


def _attempt_for_run(db: Session, run_id: str) -> AssessmentAttempt:
    attempt = db.query(AssessmentAttempt).filter_by(run_id=run_id).first()
    if attempt is None:
        raise ApiError(
            status_code=409,
            code="ASSESSMENT_NOT_FOUND",
            message="评估记录不存在",
        )
    return attempt


def _fail_assessment(
    db: Session,
    snapshot: RunSnapshot,
    *,
    code: str,
    retryable: bool,
    mark_attempt_failed: bool = True,
) -> AgentRun:
    state = deepcopy(snapshot.state)
    state["processing"] = False
    updated = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == snapshot.id,
            AgentRun.user_id == snapshot.user_id,
            AgentRun.version == snapshot.version,
        )
        .update(
            {
                AgentRun.status: AgentRunStatus.FAILED.value,
                AgentRun.state_json: state,
                AgentRun.version: snapshot.version + 1,
                AgentRun.error_code: code,
                AgentRun.retryable: retryable,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="评估流程已被其他请求更新",
        )
    if mark_attempt_failed:
        db.query(AssessmentAttempt).filter_by(run_id=snapshot.id).update(
            {AssessmentAttempt.status: AssessmentStatus.FAILED.value},
            synchronize_session=False,
        )
    db.commit()
    return _load_owned(db, snapshot.user_id, snapshot.id)


def _generate_assessment_questions(
    db: Session, snapshot: RunSnapshot, generator: Generator | None
) -> AgentRun:
    params = snapshot.state["params"]
    messages = [
        {
            "role": "system",
            "content": (
                "生成三道独立掌握评估题及每题 0-4 分可观察量规。题目覆盖理解、应用和边界，"
                "并按学习成果类型调整任务，只返回结构化 JSON。"
            ),
        },
        {"role": "user", "content": json.dumps(params, ensure_ascii=False)},
    ]
    try:
        generated = _invoke(
            generator,
            AssessmentQuestions,
            messages,
            snapshot,
            "assessment_questions",
        )
    except StructuredAIError as error:
        return _fail_assessment(db, snapshot, code=error.code, retryable=error.retryable)

    questions = generated.value.model_dump(mode="json")["questions"]
    state = deepcopy(snapshot.state)
    state.update(
        {
            "questions": questions,
            "answers": [],
            "current_index": 0,
            "step_id": "assessment-question-1",
            "processing": False,
        }
    )
    updated = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == snapshot.id,
            AgentRun.user_id == snapshot.user_id,
            AgentRun.version == snapshot.version,
        )
        .update(
            {
                AgentRun.state_json: state,
                AgentRun.version: snapshot.version + 1,
                AgentRun.token_usage: snapshot.token_usage + generated.token_usage,
                AgentRun.latency_ms: snapshot.latency_ms + generated.latency_ms,
                AgentRun.error_code: None,
                AgentRun.retryable: None,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise ApiError(status_code=409, code="AGENT_STATE_CONFLICT", message="评估流程已更新")
    attempt = _attempt_for_run(db, snapshot.id)
    attempt.questions_json = questions
    attempt.rubrics_json = [
        {"question_id": question["question_id"], "rubric": question["rubric"]}
        for question in questions
    ]
    attempt.answers_json = []
    attempt.status = AssessmentStatus.ACTIVE.value
    db.commit()
    return _load_owned(db, snapshot.user_id, snapshot.id)


def start_assessment(
    db: Session,
    *,
    user_id: int,
    node_id: int,
    request_id: str,
    session_id: str | None = None,
    generator: Generator | None = None,
    model_id: str | None = None,
) -> AgentRun:
    existing_request = (
        db.query(AgentRun)
        .filter(
            AgentRun.user_id == user_id,
            AgentRun.run_type == AgentRunType.ASSESSMENT.value,
            AgentRun.request_id == request_id,
        )
        .first()
    )
    if existing_request is not None:
        return existing_request
    node = _owned_node(db, user_id, node_id)
    if node.state == "locked":
        raise ApiError(status_code=409, code="NODE_LOCKED", message="节点尚未解锁")
    active = (
        db.query(AssessmentAttempt)
        .filter(
            AssessmentAttempt.user_id == user_id,
            AssessmentAttempt.node_id == node.id,
            AssessmentAttempt.status == AssessmentStatus.ACTIVE.value,
        )
        .first()
    )
    if active is not None:
        return active.run
    if node.state == "mastered":
        completed = (
            db.query(AssessmentAttempt)
            .filter(
                AssessmentAttempt.user_id == user_id,
                AssessmentAttempt.node_id == node.id,
                AssessmentAttempt.status == AssessmentStatus.COMPLETED.value,
            )
            .order_by(AssessmentAttempt.id.desc())
            .first()
        )
        if completed is not None:
            return completed.run
        raise ApiError(
            status_code=409,
            code="NODE_ALREADY_MASTERED",
            message="节点已经掌握",
        )

    plan = db.query(StudyPlan).filter(StudyPlan.topic_id == node.topic_id).first()
    params = {
        "node_id": node.id,
        "node_key": node.node_key,
        "node_label": node.label,
        "node_sub": node.sub or "",
        "topic": node.topic.title,
        "domain": plan.domain if plan else "general",
        "outcome_type": plan.outcome_type if plan else "concept",
    }
    run = AgentRun(
        user_id=user_id,
        session_id=session_id,
        topic_id=node.topic_id,
        run_type=AgentRunType.ASSESSMENT.value,
        status=AgentRunStatus.ASSESSING.value,
        version=1,
        state_json={
            "params": params,
            "processing": True,
            "processing_stage": "assessment_questions",
        },
        model=resolve_model_id(model_id),
        request_id=request_id,
    )
    db.add(run)
    db.flush()
    attempt = AssessmentAttempt(
        user_id=user_id,
        node_id=node.id,
        run_id=run.id,
        status=AssessmentStatus.ACTIVE.value,
        questions_json=[],
        answers_json=[],
        rubrics_json=[],
    )
    db.add(attempt)
    db.flush()
    state = deepcopy(run.state_json)
    state["attempt_id"] = attempt.id
    run.state_json = state
    snapshot = _snapshot(run)
    db.commit()
    return _generate_assessment_questions(db, snapshot, generator)


def _score_assessment(db: Session, snapshot: RunSnapshot, generator: Generator | None) -> AgentRun:
    state = deepcopy(snapshot.state)
    messages = [
        {
            "role": "system",
            "content": "严格按每题量规进行 0-4 分评分并集中返回结构化结果。",
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "params": state["params"],
                    "questions": state["questions"],
                    "answers": state["answers"],
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        scored = _invoke(generator, AssessmentScore, messages, snapshot, "assessment_score")
    except StructuredAIError as error:
        return _fail_assessment(db, snapshot, code=error.code, retryable=error.retryable)

    score = scored.value
    params = state["params"]
    expected_question_ids = {question["question_id"] for question in state["questions"]}
    scored_question_ids = {item.question_id for item in score.scores}
    if scored_question_ids != expected_question_ids:
        return _fail_assessment(
            db,
            snapshot,
            code="ASSESSMENT_SCORE_INVALID",
            retryable=True,
        )
    professional_review_required = bool(
        high_risk_notice(params["domain"], params["topic"])
        and params["outcome_type"] == "procedure"
    )
    passed = bool(
        score.total_score >= 9
        and not score.critical_misconception
        and score.evaluation_confidence >= 0.7
        and not professional_review_required
    )
    result = {
        **score.model_dump(mode="json"),
        "node_id": params["node_id"],
        "node_label": params["node_label"],
        "passed": passed,
        "professional_review_required": professional_review_required,
        "threshold": {
            "minimum_score": 9,
            "minimum_confidence": 0.7,
            "requires_no_critical_misconception": True,
        },
        "next_actions": (
            ["continue_learning", "retry_assessment"]
            if not passed
            else ["continue_plan", "revert_mastery"]
        ),
    }
    attempt = _attempt_for_run(db, snapshot.id)
    attempt.status = AssessmentStatus.COMPLETED.value
    attempt.scores_json = score.model_dump(mode="json")["scores"]
    attempt.total_score = score.total_score
    attempt.evaluation_confidence = score.evaluation_confidence
    attempt.critical_misconception = score.critical_misconception
    attempt.evidence = score.evidence
    from datetime import datetime, timezone

    attempt.completed_at = datetime.now(timezone.utc)
    node = db.get(Node, params["node_id"])
    upsert_assessment_memories(
        db,
        user_id=snapshot.user_id,
        node=node,
        weaknesses=score.weaknesses,
        passed=passed,
        confidence=score.evaluation_confidence,
    )
    state["assessment_result"] = result
    state["processing_stage"] = "assessment_mastery" if passed else "assessment_complete"
    next_version = snapshot.version + 1
    updated = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == snapshot.id,
            AgentRun.user_id == snapshot.user_id,
            AgentRun.version == snapshot.version,
        )
        .update(
            {
                AgentRun.state_json: state,
                AgentRun.result_json: result,
                AgentRun.version: next_version,
                AgentRun.token_usage: snapshot.token_usage + scored.token_usage,
                AgentRun.latency_ms: snapshot.latency_ms + scored.latency_ms,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise ApiError(status_code=409, code="AGENT_STATE_CONFLICT", message="评估流程已更新")
    db.commit()

    if passed:
        try:
            record_mastery(
                db,
                user_id=snapshot.user_id,
                node_id=params["node_id"],
                source=MasterySource.ASSESSMENT,
                request_id=f"assessment-{attempt.id}",
                assessment_id=attempt.id,
            )
        except ApiError as error:
            checkpoint = RunSnapshot(
                id=snapshot.id,
                user_id=snapshot.user_id,
                status=AgentRunStatus.ASSESSING.value,
                version=next_version,
                state=state,
                model=snapshot.model,
                token_usage=snapshot.token_usage + scored.token_usage,
                latency_ms=snapshot.latency_ms + scored.latency_ms,
            )
            return _fail_assessment(
                db,
                checkpoint,
                code=error.code,
                retryable=False,
                mark_attempt_failed=False,
            )

    state["processing"] = False
    state["processing_stage"] = None
    updated = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == snapshot.id,
            AgentRun.user_id == snapshot.user_id,
            AgentRun.version == next_version,
        )
        .update(
            {
                AgentRun.status: AgentRunStatus.COMPLETED.value,
                AgentRun.state_json: state,
                AgentRun.version: next_version + 1,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise ApiError(status_code=409, code="AGENT_STATE_CONFLICT", message="评估流程已更新")
    db.commit()
    return _load_owned(db, snapshot.user_id, snapshot.id)


def submit_assessment_answer(
    db: Session,
    *,
    user_id: int,
    run_id: str,
    step_id: str,
    version: int,
    answer: str,
    generator: Generator | None = None,
) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    state = deepcopy(run.state_json or {})
    if (
        run.run_type != AgentRunType.ASSESSMENT.value
        or run.status != AgentRunStatus.ASSESSING.value
        or run.version != version
        or state.get("step_id") != step_id
        or state.get("processing")
    ):
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="评估步骤或版本已过期",
            retryable=False,
        )
    answer = answer.strip()
    if not answer:
        raise ApiError(status_code=422, code="ANSWER_REQUIRED", message="回答不能为空")
    questions = state["questions"]
    index = state["current_index"]
    answers = [
        *state.get("answers", []),
        {"question_id": questions[index]["question_id"], "answer": answer},
    ]
    state["answers"] = answers
    state["current_index"] = index + 1
    run.version += 1
    attempt = _attempt_for_run(db, run.id)
    attempt.answers_json = answers
    if index + 1 < len(questions):
        state["step_id"] = f"assessment-question-{index + 2}"
        run.state_json = state
        db.commit()
        return _load_owned(db, user_id, run.id)
    state.update(
        {
            "step_id": None,
            "processing": True,
            "processing_stage": "assessment_score",
        }
    )
    run.state_json = state
    snapshot = _snapshot(run)
    db.commit()
    return _score_assessment(db, snapshot, generator)


def retry_assessment(
    db: Session,
    *,
    user_id: int,
    run_id: str,
    version: int | None = None,
    generator: Generator | None = None,
) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    require_version(db, run, version)
    if (
        run.run_type != AgentRunType.ASSESSMENT.value
        or run.status != AgentRunStatus.FAILED.value
        or not run.retryable
    ):
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_RETRY_NOT_ALLOWED",
            message="当前评估不可重试",
        )
    state = deepcopy(run.state_json or {})
    stage = state.get("processing_stage")
    run.status = transition(run.status, AgentRunStatus.ASSESSING).value
    run.version += 1
    run.error_code = None
    run.retryable = None
    state["processing"] = True
    run.state_json = state
    attempt = _attempt_for_run(db, run.id)
    attempt.status = AssessmentStatus.ACTIVE.value
    snapshot = _snapshot(run)
    db.commit()
    if stage == "assessment_questions":
        return _generate_assessment_questions(db, snapshot, generator)
    if stage == "assessment_score":
        return _score_assessment(db, snapshot, generator)
    return _fail_assessment(db, snapshot, code="ASSESSMENT_STAGE_UNKNOWN", retryable=False)


def cancel_assessment(db: Session, *, user_id: int, run_id: str) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    if run.status == AgentRunStatus.CANCELLED.value:
        return run
    run.status = transition(run.status, AgentRunStatus.CANCELLED).value
    state = deepcopy(run.state_json or {})
    state["processing"] = False
    run.state_json = state
    run.version += 1
    attempt = _attempt_for_run(db, run.id)
    attempt.status = AssessmentStatus.CANCELLED.value
    db.commit()
    return _load_owned(db, user_id, run.id)
