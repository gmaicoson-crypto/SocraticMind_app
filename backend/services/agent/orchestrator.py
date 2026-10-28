import json
from copy import deepcopy
from typing import Any, Callable

from sqlalchemy.orm import Session

from core.ai_client import resolve_model_id
from core.errors import ApiError
from models import AgentRun, LearnerMemory, Node, StudyPlan, StudyPlanItem, Topic
from models.enums import AgentRunStatus, AgentRunType, MemorySource
from schemas.agent import OnboardingRequest, TopicPlanRequest
from schemas.structured_ai import (
    DiagnosticQuestions,
    DiagnosticScore,
    PersonalizedGraphDraft,
)
from services.graph_validation import GraphValidationError, prepare_graph
from services.planning import build_schedule, today_in_timezone

from .onboarding_creation import reserve_onboarding
from .run_store import (
    RunSnapshot,
    _begin_processing,
    _conditional_save,
    _load_owned,
    _mark_failed,
    _snapshot,
    cancel_run as cancel_run,
    get_run as get_run,
    require_version,
)
from .state_machine import transition
from .structured_ai import (
    RunContext,
    StructuredAIError,
    StructuredResult,
    generate_structured,
    high_risk_notice,
)


Generator = Callable[[type, list[dict], RunContext], StructuredResult]


def _invoke(
    generator: Generator | None,
    schema: type,
    messages: list[dict],
    snapshot: RunSnapshot,
    call_type: str,
) -> StructuredResult:
    implementation = generator or generate_structured
    return implementation(
        schema,
        messages,
        RunContext(run_id=snapshot.id, call_type=call_type, model=snapshot.model),
    )


def _generate_questions(
    db: Session, snapshot: RunSnapshot, generator: Generator | None
) -> AgentRun:
    params = snapshot.state["params"]
    messages = [
        {
            "role": "system",
            "content": (
                "生成三道诊断题，dimension 依次覆盖 prior_knowledge、application、limits。"
                "题目应适配给定领域和学习成果类型，只返回结构化 JSON。"
            ),
        },
        {"role": "user", "content": json.dumps(params, ensure_ascii=False)},
    ]
    try:
        result = _invoke(generator, DiagnosticQuestions, messages, snapshot, "diagnostic_questions")
    except StructuredAIError as error:
        return _mark_failed(db, snapshot, code=error.code, retryable=error.retryable)

    state = deepcopy(snapshot.state)
    state.update(
        {
            "questions": result.value.model_dump(mode="json")["questions"],
            "answers": [],
            "current_index": 0,
            "step_id": "diagnostic-question-1",
            "processing": False,
        }
    )
    saved = _conditional_save(
        db,
        snapshot,
        status=AgentRunStatus.DIAGNOSING,
        state=state,
        ai_result=result,
    )
    return _load_owned(db, saved.user_id, saved.id)


def _diagnostic_messages(state: dict[str, Any]) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "根据三道题和回答集中评分，返回结构化诊断结果。",
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "params": state["params"],
                    "questions": state.get("questions", []),
                    "answers": state.get("answers", []),
                },
                ensure_ascii=False,
            ),
        },
    ]


def _graph_messages(state: dict[str, Any]) -> list[dict]:
    params = state["params"]
    return [
        {
            "role": "system",
            "content": (
                "生成 6 到 10 个严格树结构的学习节点：有且只有一个根节点，每个非根节点必须且只能有一个父节点，"
                "根节点至少有两个直接子节点，整棵树至少有两个分支节点和三个叶子节点，最长路径不超过四层，禁止单链结构。"
                "节点之间无环，每个节点预计 10 到 120 分钟，结构和题材必须适配领域及学习成果类型，只返回结构化 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"params": params, "diagnostic": state.get("diagnostic_result")},
                ensure_ascii=False,
            ),
        },
    ]


def _existing_topic_preview(state: dict[str, Any]) -> dict[str, Any]:
    params = state["params"]
    graph = deepcopy(state["node_snapshot"])
    start_date, effective_timezone = today_in_timezone(params.get("timezone"))
    target_date = params.get("target_date")
    if target_date:
        from datetime import date

        target_date = date.fromisoformat(target_date)
    plan = build_schedule(
        graph,
        daily_minutes=params["daily_minutes"],
        start_date=start_date,
        target_date=target_date,
        timezone=effective_timezone,
        skip_node_keys={node["key"] for node in graph if node["state"] == "mastered"},
    )
    return {
        "existing_topic_id": params["existing_topic_id"],
        "topic": params["topic"],
        "emoji": state["topic_emoji"],
        "goal": params["goal"],
        "domain": params["domain"],
        "outcome_type": params["outcome_type"],
        "diagnostic": state.get("diagnostic_result"),
        "nodes": graph,
        "plan_items": [
            {
                "node_key": item.node_key,
                "scheduled_date": item.scheduled_date.isoformat(),
                "day_order": item.day_order,
                "estimated_minutes": item.estimated_minutes,
                "status": item.status,
            }
            for item in plan.items
        ],
        "total_minutes": plan.total_minutes,
        "daily_minutes": params["daily_minutes"],
        "start_date": start_date.isoformat(),
        "estimated_end_date": plan.estimated_end_date.isoformat(),
        "target_date": params.get("target_date"),
        "will_miss_target": plan.will_miss_target,
        "delay_days": plan.delay_days,
        "effective_timezone": plan.effective_timezone,
        "risk_notice": high_risk_notice(params["domain"], params["topic"]),
    }


def _generate_preview(db: Session, snapshot: RunSnapshot, generator: Generator | None) -> AgentRun:
    current = snapshot
    state = deepcopy(current.state)
    if state.get("answers") and not state.get("diagnostic_result"):
        try:
            score = _invoke(
                generator,
                DiagnosticScore,
                _diagnostic_messages(state),
                current,
                "diagnostic_score",
            )
        except StructuredAIError as error:
            return _mark_failed(db, current, code=error.code, retryable=error.retryable)
        state["diagnostic_result"] = score.value.model_dump(mode="json")
        state["processing_stage"] = "graph_draft"
        current = _conditional_save(
            db,
            current,
            status=AgentRunStatus.DRAFTING,
            state=state,
            ai_result=score,
        )

    if state["params"].get("existing_topic_id"):
        try:
            preview = _existing_topic_preview(state)
        except (GraphValidationError, ValueError):
            return _mark_failed(db, current, code="EXISTING_GRAPH_INVALID", retryable=False)
        state["preview"] = preview
        state["processing"] = False
        state["processing_stage"] = None
        saved = _conditional_save(
            db,
            current,
            status=AgentRunStatus.AWAITING_CONFIRMATION,
            state=state,
        )
        return _load_owned(db, saved.user_id, saved.id)

    try:
        graph_result = _invoke(
            generator,
            PersonalizedGraphDraft,
            _graph_messages(state),
            current,
            "personalized_graph",
        )
        graph = prepare_graph(graph_result.value.model_dump(mode="json")["nodes"])
    except StructuredAIError as error:
        return _mark_failed(db, current, code=error.code, retryable=error.retryable)
    except GraphValidationError:
        return _mark_failed(db, current, code="GRAPH_INVALID", retryable=True)

    params = state["params"]
    start_date, effective_timezone = today_in_timezone(params.get("timezone"))
    target_date = params.get("target_date")
    if target_date:
        from datetime import date

        target_date = date.fromisoformat(target_date)
    plan = build_schedule(
        graph,
        daily_minutes=params["daily_minutes"],
        start_date=start_date,
        target_date=target_date,
        timezone=effective_timezone,
    )
    preview = {
        "topic": params["topic"],
        "emoji": graph_result.value.emoji,
        "goal": params["goal"],
        "domain": params["domain"],
        "outcome_type": params["outcome_type"],
        "diagnostic": state.get("diagnostic_result"),
        "nodes": graph,
        "plan_items": [
            {
                "node_key": item.node_key,
                "scheduled_date": item.scheduled_date.isoformat(),
                "day_order": item.day_order,
                "estimated_minutes": item.estimated_minutes,
                "status": item.status,
            }
            for item in plan.items
        ],
        "total_minutes": plan.total_minutes,
        "daily_minutes": params["daily_minutes"],
        "start_date": start_date.isoformat(),
        "estimated_end_date": plan.estimated_end_date.isoformat(),
        "target_date": params.get("target_date"),
        "will_miss_target": plan.will_miss_target,
        "delay_days": plan.delay_days,
        "effective_timezone": plan.effective_timezone,
        "risk_notice": high_risk_notice(params["domain"], params["topic"]),
    }
    state["preview"] = preview
    state["processing"] = False
    state["processing_stage"] = None
    saved = _conditional_save(
        db,
        current,
        status=AgentRunStatus.AWAITING_CONFIRMATION,
        state=state,
        ai_result=graph_result,
    )
    return _load_owned(db, saved.user_id, saved.id)


def start_onboarding(
    db: Session,
    *,
    user_id: int,
    request: OnboardingRequest,
    generator: Generator | None = None,
    model_id: str | None = None,
) -> AgentRun:
    run, snapshot = reserve_onboarding(db, user_id=user_id, request=request, model_id=model_id)
    if snapshot is None:
        return run
    if request.use_diagnostic:
        return _generate_questions(db, snapshot, generator)
    return _generate_preview(db, snapshot, generator)


def _serialize_node_snapshot(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "key": node.node_key,
        "label": node.label,
        "sub": node.sub or "",
        "state": node.state,
        "x": node.x,
        "y": node.y,
        "parent_keys": [key.strip() for key in (node.parent_keys or "").split(",") if key.strip()],
        "estimated_minutes": node.estimated_minutes,
    }


def start_topic_plan(
    db: Session,
    *,
    user_id: int,
    topic_id: int,
    request: TopicPlanRequest,
    generator: Generator | None = None,
    model_id: str | None = None,
) -> AgentRun:
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.user_id == user_id).first()
    if topic is None:
        raise ApiError(status_code=404, code="TOPIC_NOT_FOUND", message="主题不存在")
    if db.query(StudyPlan.id).filter(StudyPlan.topic_id == topic.id).first():
        raise ApiError(status_code=409, code="PLAN_ALREADY_EXISTS", message="主题已有学习计划")
    nodes = db.query(Node).filter(Node.topic_id == topic.id).order_by(Node.id).all()
    if not nodes:
        raise ApiError(status_code=409, code="TOPIC_HAS_NO_NODES", message="主题没有可排期节点")

    params = request.model_dump(mode="json")
    params.update({"topic": topic.title, "existing_topic_id": topic.id})
    run = AgentRun(
        user_id=user_id,
        session_id=request.session_id,
        topic_id=topic.id,
        run_type=AgentRunType.TOPIC_PLAN.value,
        status=AgentRunStatus.COLLECTING.value,
        state_json={
            "params": params,
            "processing": False,
            "topic_emoji": topic.emoji,
            "node_snapshot": [_serialize_node_snapshot(node) for node in nodes],
        },
        model=resolve_model_id(model_id or request.model),
    )
    db.add(run)
    db.flush()
    run_id = run.id
    db.commit()
    if request.use_diagnostic:
        snapshot = _begin_processing(
            db,
            user_id=user_id,
            run_id=run_id,
            target_status=AgentRunStatus.DIAGNOSING,
            stage="diagnostic_questions",
        )
        return _generate_questions(db, snapshot, generator)
    snapshot = _begin_processing(
        db,
        user_id=user_id,
        run_id=run_id,
        target_status=AgentRunStatus.DRAFTING,
        stage="existing_plan",
    )
    return _generate_preview(db, snapshot, generator)


def update_run_parameters(
    db: Session,
    *,
    user_id: int,
    run_id: str,
    updates: dict[str, Any],
    version: int | None = None,
    generator: Generator | None = None,
) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    require_version(db, run, version)
    if run.status not in {
        AgentRunStatus.COLLECTING.value,
        AgentRunStatus.AWAITING_CONFIRMATION.value,
    }:
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="当前阶段不能修改计划参数",
            retryable=False,
        )
    state = deepcopy(run.state_json or {})
    params = deepcopy(state["params"])
    params.update(updates)
    state["params"] = params
    state.pop("preview", None)
    state["processing"] = True
    state["processing_stage"] = (
        "existing_plan" if params.get("existing_topic_id") else "graph_draft"
    )
    run.status = transition(run.status, AgentRunStatus.DRAFTING).value
    run.state_json = state
    run.version += 1
    snapshot = _snapshot(run)
    db.commit()
    return _generate_preview(db, snapshot, generator)


def submit_answer(
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
        run.status != AgentRunStatus.DIAGNOSING.value
        or run.version != version
        or state.get("step_id") != step_id
        or state.get("processing")
    ):
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="问题步骤或版本已过期，请刷新后重试",
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
    if index + 1 < len(questions):
        state["step_id"] = f"diagnostic-question-{index + 2}"
        run.state_json = state
        db.commit()
        return _load_owned(db, user_id, run_id)

    run.status = transition(run.status, AgentRunStatus.DRAFTING).value
    state.update(
        {
            "step_id": None,
            "processing": True,
            "processing_stage": "diagnostic_score",
        }
    )
    run.state_json = state
    snapshot = _snapshot(run)
    db.commit()
    return _generate_preview(db, snapshot, generator)


def retry_run(
    db: Session,
    *,
    user_id: int,
    run_id: str,
    version: int | None = None,
    generator: Generator | None = None,
) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    require_version(db, run, version)
    if run.status != AgentRunStatus.FAILED.value or not run.retryable:
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_RETRY_NOT_ALLOWED",
            message="当前流程不可重试",
            retryable=False,
        )
    state = deepcopy(run.state_json or {})
    stage = state.get("processing_stage")
    target = (
        AgentRunStatus.DIAGNOSING if stage == "diagnostic_questions" else AgentRunStatus.DRAFTING
    )
    run.status = transition(run.status, target).value
    state["processing"] = True
    run.state_json = state
    run.error_code = None
    run.retryable = None
    run.version += 1
    snapshot = _snapshot(run)
    db.commit()
    if stage == "diagnostic_questions":
        return _generate_questions(db, snapshot, generator)
    if stage in {"diagnostic_score", "graph_draft", "existing_plan"}:
        return _generate_preview(db, snapshot, generator)
    return _mark_failed(db, snapshot, code="AGENT_STAGE_UNKNOWN", retryable=False)


def confirm_run(
    db: Session,
    *,
    user_id: int,
    run_id: str,
    request_id: str,
    version: int | None = None,
) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    if run.status == AgentRunStatus.COMPLETED.value:
        return run
    require_version(db, run, version)
    if run.status != AgentRunStatus.AWAITING_CONFIRMATION.value:
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="当前流程不能确认",
            retryable=False,
        )
    state = deepcopy(run.state_json or {})
    preview = state.get("preview")
    if not preview:
        raise ApiError(status_code=409, code="PREVIEW_NOT_READY", message="计划预览尚未生成")

    from datetime import date

    existing_topic_id = state["params"].get("existing_topic_id")
    if existing_topic_id:
        topic = (
            db.query(Topic)
            .filter(Topic.id == existing_topic_id, Topic.user_id == user_id)
            .with_for_update()
            .first()
        )
        if topic is None:
            db.rollback()
            raise ApiError(status_code=404, code="TOPIC_NOT_FOUND", message="主题不存在")
        live_nodes = (
            db.query(Node)
            .filter(Node.topic_id == topic.id)
            .order_by(Node.id)
            .with_for_update()
            .all()
        )
        if [_serialize_node_snapshot(node) for node in live_nodes] != state["node_snapshot"]:
            db.rollback()
            raise ApiError(
                status_code=409,
                code="AGENT_STATE_CONFLICT",
                message="主题节点已变化，请重新生成计划预览",
                retryable=False,
            )
        if db.query(StudyPlan.id).filter(StudyPlan.topic_id == topic.id).first():
            db.rollback()
            raise ApiError(
                status_code=409,
                code="PLAN_ALREADY_EXISTS",
                message="主题已有学习计划",
            )
        nodes_by_key = {node.node_key: node for node in live_nodes}
    else:
        topic = Topic(
            user_id=user_id,
            title=preview["topic"],
            emoji=preview.get("emoji") or "📚",
        )
        db.add(topic)
        db.flush()
        nodes_by_key: dict[str, Node] = {}
        for draft in preview["nodes"]:
            node = Node(
                topic_id=topic.id,
                node_key=draft["key"],
                label=draft["label"],
                sub=draft.get("sub", ""),
                state="available" if not draft.get("parent_keys") else "locked",
                x=draft["x"],
                y=draft["y"],
                parent_keys=",".join(draft.get("parent_keys", [])),
                estimated_minutes=draft["estimated_minutes"],
            )
            db.add(node)
            nodes_by_key[node.node_key] = node
        db.flush()
    plan = StudyPlan(
        user_id=user_id,
        topic_id=topic.id,
        goal=preview["goal"],
        domain=preview["domain"],
        outcome_type=preview["outcome_type"],
        daily_minutes=state["params"]["daily_minutes"],
        timezone=preview["effective_timezone"],
        start_date=date.fromisoformat(preview["start_date"]),
        target_date=(
            date.fromisoformat(preview["target_date"]) if preview.get("target_date") else None
        ),
        estimated_end_date=date.fromisoformat(preview["estimated_end_date"]),
        status="active",
    )
    db.add(plan)
    db.flush()
    for draft in preview["plan_items"]:
        db.add(
            StudyPlanItem(
                plan_id=plan.id,
                node_id=nodes_by_key[draft["node_key"]].id,
                scheduled_date=date.fromisoformat(draft["scheduled_date"]),
                day_order=draft["day_order"],
                estimated_minutes=draft["estimated_minutes"],
                status=draft["status"],
            )
        )

    params = state["params"]
    db.add_all(
        [
            LearnerMemory(
                user_id=user_id,
                topic_id=topic.id,
                kind="goal",
                content=params["goal"],
                source=MemorySource.USER.value,
            ),
            LearnerMemory(
                user_id=user_id,
                topic_id=topic.id,
                kind="background",
                content=f"自报熟悉度：{params['familiarity']}",
                source=MemorySource.USER.value,
            ),
        ]
    )

    diagnostic = state.get("diagnostic_result")
    if diagnostic:
        for kind, values in (
            ("strength", diagnostic.get("strengths", [])),
            ("weakness", diagnostic.get("weaknesses", [])),
        ):
            for content in values:
                db.add(
                    LearnerMemory(
                        user_id=user_id,
                        topic_id=topic.id,
                        kind=kind,
                        content=str(content)[:300],
                        source=MemorySource.DIAGNOSTIC.value,
                    )
                )

    run.status = transition(run.status, AgentRunStatus.COMPLETED).value
    run.topic_id = topic.id
    run.request_id = request_id
    run.result_json = {"topic_id": topic.id, "plan_id": plan.id}
    run.version += 1
    db.commit()
    return _load_owned(db, user_id, run_id)
