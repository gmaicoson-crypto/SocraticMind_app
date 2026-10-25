"""Use independent real MySQL transactions to exercise run arbitration and fencing."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from core.errors import ApiError
from models import AgentRun, StudyPlan, Topic, User
from schemas.agent import OnboardingRequest
from services.agent.orchestrator import (
    cancel_run,
    confirm_run,
    get_run,
    start_onboarding,
    update_run_parameters,
)
from services.agent.structured_ai import StructuredAIError
from test_mysql_baseline import mysql_database as mysql_database
from tests.p0.test_agent_api import fake_generator, onboarding_payload


def prepare(mysql_database):
    engine, config, _ = mysql_database
    command.upgrade(config, "head")
    with Session(engine) as db:
        user = User(username="流程测试", email="run@example.test", hashed_password="synthetic")
        db.add(user)
        db.commit()
        user_id = user.id
    request = OnboardingRequest(**{**onboarding_payload(), "run_id": str(uuid4())})
    return engine, user_id, request


def test_mysql_concurrent_onboarding_create_and_confirm(mysql_database):
    engine, user_id, request = prepare(mysql_database)
    competing = Barrier(2)
    counter_lock = Lock()
    calls = []

    def generate(*arguments):
        with counter_lock:
            calls.append(1)
        return fake_generator(*arguments)

    def create():
        with Session(engine) as db:
            # Both requests must miss the initial lookup before either INSERT commits.
            event.listen(db, "before_flush", lambda *_: competing.wait(timeout=10), once=True)
            run = start_onboarding(db, user_id=user_id, request=request, generator=generate)
            return run.id

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: create(), range(2)))
    run_id = str(request.run_id)
    assert results == [run_id, run_id]
    assert len(calls) == 1
    with Session(engine) as db:
        run = get_run(db, user_id=user_id, run_id=run_id)
        version = run.version
        assert run.status == "awaiting_confirmation"
        assert db.query(AgentRun).count() == 1

    confirming = Barrier(2)

    def confirm():
        with Session(engine) as db:
            confirming.wait(timeout=10)
            run = confirm_run(
                db, user_id=user_id, run_id=run_id, request_id="confirm", version=version
            )
            return run.result_json

    with ThreadPoolExecutor(max_workers=2) as workers:
        confirmed = list(workers.map(lambda _: confirm(), range(2)))
    assert confirmed[0] == confirmed[1]
    with Session(engine) as db:
        assert db.query(Topic).count() == db.query(StudyPlan).count() == 1


def test_mysql_confirmation_uses_current_version_despite_old_read_snapshot(mysql_database):
    engine, user_id, request = prepare(mysql_database)
    with Session(engine) as reader:
        run = start_onboarding(reader, user_id=user_id, request=request, generator=fake_generator)
        run_id, old_version = run.id, run.version
        with Session(engine) as writer:
            update_run_parameters(
                writer,
                user_id=user_id,
                run_id=run_id,
                version=old_version,
                updates={"daily_minutes": 10},
                generator=fake_generator,
            )
        with pytest.raises(ApiError) as conflict:
            confirm_run(
                reader, user_id=user_id, run_id=run_id, request_id="stale", version=old_version
            )
        assert conflict.value.code == "AGENT_STATE_CONFLICT"
        assert reader.query(Topic).count() == 0
        assert (
            get_run(reader, user_id=user_id, run_id=run_id).state_json["params"]["daily_minutes"]
            == 10
        )


def test_mysql_cancel_fences_late_onboarding_model_result(mysql_database):
    engine, user_id, request = prepare(mysql_database)
    started, release = Event(), Event()

    def generate(*arguments):
        started.set()
        assert release.wait(timeout=10)
        return fake_generator(*arguments)

    def create():
        with Session(engine) as db:
            return start_onboarding(db, user_id=user_id, request=request, generator=generate)

    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(create)
        try:
            assert started.wait(timeout=10)
            with Session(engine) as db:
                run = get_run(db, user_id=user_id, run_id=str(request.run_id))
                assert run.status == "drafting"
                assert run.state_json["processing"] is True
                cancelled = cancel_run(db, user_id=user_id, run_id=run.id)
                version = cancelled.version
        finally:
            release.set()
        with pytest.raises(ApiError) as conflict:
            future.result(timeout=10)
        assert conflict.value.code == "AGENT_STATE_CONFLICT"
    with Session(engine) as db:
        run = get_run(db, user_id=user_id, run_id=str(request.run_id))
        assert run.status == "cancelled" and run.version == version
        assert run.state_json.get("preview") is None
        assert db.query(Topic).count() == db.query(StudyPlan).count() == 0


@pytest.mark.parametrize("model_fails", [False, True])
def test_mysql_cancel_after_creation_commit_preserves_terminal_version(mysql_database, model_fails):
    engine, user_id, request = prepare(mysql_database)
    cancelled_versions = []
    with Session(engine) as creator:

        def after_commit(_):
            with Session(engine) as peer:
                run = cancel_run(peer, user_id=user_id, run_id=str(request.run_id))
                cancelled_versions.append(run.version)

        event.listen(creator, "after_commit", after_commit, once=True)

        def generate(*arguments):
            assert not creator.in_transaction()
            if model_fails:
                raise StructuredAIError("AI_TIMEOUT", "synthetic timeout", retryable=True)
            return fake_generator(*arguments)

        with pytest.raises(ApiError) as conflict:
            start_onboarding(creator, user_id=user_id, request=request, generator=generate)
        assert conflict.value.code == "AGENT_STATE_CONFLICT"
    with Session(engine) as reader:
        run = get_run(reader, user_id=user_id, run_id=str(request.run_id))
        assert cancelled_versions == [2]
        assert run.status == "cancelled" and run.version == 2
        assert run.state_json["processing"] is False
        assert run.error_code is None
        assert run.state_json.get("preview") is None
        assert reader.query(Topic).count() == reader.query(StudyPlan).count() == 0
