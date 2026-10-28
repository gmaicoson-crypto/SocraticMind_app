"""Reserve one onboarding run before model work; replays never invoke the model."""

import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.ai_client import resolve_model_id
from core.errors import ApiError
from models import AgentRun
from models.enums import AgentRunStatus, AgentRunType
from schemas.agent import OnboardingRequest
from .run_store import RunSnapshot, _snapshot, cancel_run


def _replay(run: AgentRun, user_id: int, fingerprint: str) -> AgentRun:
    if run.user_id != user_id or run.run_type != AgentRunType.ONBOARDING.value:
        raise ApiError(status_code=404, code="RUN_NOT_FOUND", message="流程不存在")
    if (
        run.status == AgentRunStatus.CANCELLED.value
        and (run.state_json or {}).get("creation_cancelled") is True
    ):
        return run
    if (run.state_json or {}).get("creation_fingerprint") != fingerprint:
        raise ApiError(
            status_code=409,
            code="AGENT_REQUEST_CONFLICT",
            message="流程标识已用于其他创建请求，请恢复原流程或重新创建",
            retryable=False,
        )
    return run


def reserve_onboarding(
    db: Session,
    *,
    user_id: int,
    request: OnboardingRequest,
    model_id: str | None,
) -> tuple[AgentRun, RunSnapshot | None]:
    params = request.model_dump(mode="json", exclude={"run_id"})
    fingerprint = hashlib.sha256(
        json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    run_id = str(request.run_id) if request.run_id else None
    if run_id:
        existing = db.get(AgentRun, run_id, populate_existing=True)
        if existing is not None:
            return _replay(existing, user_id, fingerprint), None
    diagnosing = request.use_diagnostic
    run = AgentRun(
        id=run_id,
        user_id=user_id,
        session_id=request.session_id,
        run_type=AgentRunType.ONBOARDING.value,
        status=AgentRunStatus.DIAGNOSING.value if diagnosing else AgentRunStatus.DRAFTING.value,
        version=1,
        state_json={
            "params": params,
            "processing": True,
            "processing_stage": "diagnostic_questions" if diagnosing else "graph_draft",
            "creation_fingerprint": fingerprint,
        },
        model=resolve_model_id(model_id or request.model),
    )
    db.add(run)
    try:
        db.flush()
        # Capture our committed version before commit expires the ORM object. A later
        # refresh may see another caller's cancellation and must not grant its version
        # to this worker's result/failure writer.
        snapshot = _snapshot(run)
        db.commit()
    except IntegrityError:
        # The primary key arbitrates concurrent creation across workers. End the failed
        # transaction before reading the winner; do not swallow unrelated DB failures.
        db.rollback()
        existing = db.get(AgentRun, run_id, populate_existing=True) if run_id else None
        if existing is None:
            raise
        return _replay(existing, user_id, fingerprint), None
    return run, snapshot


def cancel_onboarding(db: Session, *, user_id: int, run_id: str) -> AgentRun:
    """Persist cancellation even before a delayed create reaches this server.

    Do not lock a missing row: the primary key arbitrates concurrent inserts. If
    creation wins, roll back the failed insert before locking/cancelling its run.
    The minimal terminal record must remain while delayed requests are possible.
    """
    if db.get(AgentRun, run_id, populate_existing=True) is None:
        run = AgentRun(
            id=run_id,
            user_id=user_id,
            run_type=AgentRunType.ONBOARDING.value,
            status=AgentRunStatus.CANCELLED.value,
            version=1,
            state_json={"creation_cancelled": True, "processing": False},
        )
        db.add(run)
        try:
            db.commit()
            return run
        except IntegrityError:
            db.rollback()
            if db.get(AgentRun, run_id, populate_existing=True) is None:
                raise
    return cancel_run(db, user_id=user_id, run_id=run_id, run_type=AgentRunType.ONBOARDING)
