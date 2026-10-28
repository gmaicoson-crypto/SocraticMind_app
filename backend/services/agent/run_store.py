"""Owned run snapshots and versioned persistence shared by learning flows."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.errors import ApiError
from models import AgentRun
from models.enums import AgentRunStatus, AgentRunType
from .state_machine import transition
from .structured_ai import StructuredResult


@dataclass(frozen=True)
class RunSnapshot:
    id: str
    user_id: int
    status: str
    version: int
    state: dict[str, Any]
    model: str | None
    token_usage: int
    latency_ms: int


def _snapshot(run: AgentRun) -> RunSnapshot:
    return RunSnapshot(
        id=run.id,
        user_id=run.user_id,
        status=run.status,
        version=run.version,
        state=deepcopy(run.state_json or {}),
        model=run.model,
        token_usage=run.token_usage or 0,
        latency_ms=run.latency_ms or 0,
    )


def _load_owned(db: Session, user_id: int, run_id: str, *, for_update: bool = False) -> AgentRun:
    query = (
        db.query(AgentRun)
        .populate_existing()
        .filter(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    if for_update:
        query = query.with_for_update()
    run = query.first()
    if run is None:
        raise ApiError(status_code=404, code="RUN_NOT_FOUND", message="流程不存在")
    return run


def get_run(db: Session, *, user_id: int, run_id: str) -> AgentRun:
    return _load_owned(db, user_id, run_id)


def _begin_processing(
    db: Session,
    *,
    user_id: int,
    run_id: str,
    target_status: AgentRunStatus,
    stage: str,
    state_updates: dict[str, Any] | None = None,
) -> RunSnapshot:
    run = _load_owned(db, user_id, run_id, for_update=True)
    run.status = transition(run.status, target_status).value
    state = deepcopy(run.state_json or {})
    state.update(state_updates or {})
    state["processing"] = True
    state["processing_stage"] = stage
    run.state_json = state
    run.error_code = None
    run.retryable = None
    run.version += 1
    snapshot = _snapshot(run)
    db.commit()
    return snapshot


def _conditional_save(
    db: Session,
    snapshot: RunSnapshot,
    *,
    status: AgentRunStatus,
    state: dict[str, Any],
    ai_result: StructuredResult | None = None,
) -> RunSnapshot:
    transition(snapshot.status, status)
    next_version = snapshot.version + 1
    token_usage = snapshot.token_usage + (ai_result.token_usage if ai_result else 0)
    latency_ms = snapshot.latency_ms + (ai_result.latency_ms if ai_result else 0)
    updated = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == snapshot.id,
            AgentRun.user_id == snapshot.user_id,
            AgentRun.version == snapshot.version,
        )
        .update(
            {
                AgentRun.status: status.value,
                AgentRun.state_json: state,
                AgentRun.version: next_version,
                AgentRun.token_usage: token_usage,
                AgentRun.latency_ms: latency_ms,
                AgentRun.error_code: None,
                AgentRun.retryable: None,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="流程已被其他请求更新，请刷新后重试",
            retryable=False,
        )
    next_snapshot = RunSnapshot(
        id=snapshot.id,
        user_id=snapshot.user_id,
        status=status.value,
        version=next_version,
        state=deepcopy(state),
        model=snapshot.model,
        token_usage=token_usage,
        latency_ms=latency_ms,
    )
    db.commit()
    return next_snapshot


def _mark_failed(
    db: Session,
    snapshot: RunSnapshot,
    *,
    code: str,
    retryable: bool,
) -> AgentRun:
    transition(snapshot.status, AgentRunStatus.FAILED)
    state = deepcopy(snapshot.state)
    state["processing"] = False
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
                AgentRun.status: AgentRunStatus.FAILED.value,
                AgentRun.state_json: state,
                AgentRun.version: next_version,
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
            message="流程已被其他请求更新，请刷新后重试",
        )
    db.commit()
    return _load_owned(db, snapshot.user_id, snapshot.id)


def require_version(db: Session, run: AgentRun, version: int | None) -> None:
    if version is not None and run.version != version:
        db.rollback()
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="流程版本已过期，请刷新后重试",
            retryable=False,
        )


def cancel_run(
    db: Session, *, user_id: int, run_id: str, run_type: AgentRunType | None = None
) -> AgentRun:
    run = _load_owned(db, user_id, run_id, for_update=True)
    if run_type is not None and run.run_type != run_type.value:
        raise ApiError(status_code=404, code="RUN_NOT_FOUND", message="流程不存在")
    if run.status == AgentRunStatus.CANCELLED.value:
        return run
    run.status = transition(run.status, AgentRunStatus.CANCELLED).value
    state = deepcopy(run.state_json or {})
    state["processing"] = False
    run.state_json = state
    run.version += 1
    db.commit()
    return _load_owned(db, user_id, run_id)
