"""Unknown creation cancellation must arbitrate against real, independent transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from core.errors import ApiError
from models import AgentRun, StudyPlan, Topic
from services.agent.onboarding_creation import cancel_onboarding
from services.agent.orchestrator import get_run, start_onboarding
from services.agent.structured_ai import StructuredAIError
from test_mysql_baseline import mysql_database as mysql_database
from test_mysql_onboarding_recovery import prepare
from tests.p0.test_agent_api import fake_generator


def test_mysql_cancel_wins_despite_creator_old_missing_snapshot(mysql_database):
    engine, user_id, request = prepare(mysql_database)
    run_id = str(request.run_id)
    with Session(engine) as creator:
        assert creator.get(AgentRun, run_id) is None
        with Session(engine) as canceller:
            assert (
                cancel_onboarding(canceller, user_id=user_id, run_id=run_id).status == "cancelled"
            )
        # REPEATABLE READ still misses the row. Its INSERT must lose at the unique key.
        assert creator.get(AgentRun, run_id) is None
        inserts = []
        event.listen(creator, "before_flush", lambda *_: inserts.append(1), once=True)

        def forbidden(*_args):
            pytest.fail("The lost INSERT must not start a model")

        run = start_onboarding(creator, user_id=user_id, request=request, generator=forbidden)
        assert inserts == [1]
        assert run.status == "cancelled" and run.version == 1
        assert run.state_json == {"creation_cancelled": True, "processing": False}
        assert creator.query(AgentRun).count() == 1
        assert creator.query(Topic).count() == creator.query(StudyPlan).count() == 0


def test_mysql_create_wins_before_cancel_reservation_insert(mysql_database):
    engine, user_id, request = prepare(mysql_database)
    run_id = str(request.run_id)
    versions = []
    with Session(engine) as canceller:

        def create_before_cancel_insert(*_args):
            with Session(engine) as creator:
                run = start_onboarding(
                    creator, user_id=user_id, request=request, generator=fake_generator
                )
                versions.append(run.version)

        event.listen(canceller, "before_flush", create_before_cancel_insert, once=True)
        run = cancel_onboarding(canceller, user_id=user_id, run_id=run_id)
        assert run.status == "cancelled" and run.version == versions[0] + 1
        assert run.state_json.get("creation_cancelled") is None
        assert run.state_json["processing"] is False
        assert "creation_fingerprint" in run.state_json
        assert canceller.query(AgentRun).count() == 1
        assert canceller.query(Topic).count() == canceller.query(StudyPlan).count() == 0


def test_mysql_concurrent_cancel_reservations_return_one_terminal_record(mysql_database):
    engine, user_id, request = prepare(mysql_database)
    competing = Barrier(2)

    def cancel():
        with Session(engine) as db:
            event.listen(db, "before_flush", lambda *_: competing.wait(timeout=10), once=True)
            run = cancel_onboarding(db, user_id=user_id, run_id=str(request.run_id))
            return run.id, run.status, run.version

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: cancel(), range(2)))
    assert results == [(str(request.run_id), "cancelled", 1)] * 2
    with Session(engine) as db:
        assert db.query(AgentRun).count() == 1


@pytest.mark.parametrize("model_fails", [False, True])
def test_mysql_onboarding_cancel_fences_inflight_success_and_failure(mysql_database, model_fails):
    engine, user_id, request = prepare(mysql_database)
    started, release = Event(), Event()

    def generate(*arguments):
        started.set()
        assert release.wait(timeout=10)
        if model_fails:
            raise StructuredAIError("AI_TIMEOUT", "synthetic", retryable=True)
        return fake_generator(*arguments)

    def create():
        with Session(engine) as db:
            return start_onboarding(db, user_id=user_id, request=request, generator=generate)

    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(create)
        try:
            assert started.wait(timeout=10)
            with Session(engine) as db:
                run = cancel_onboarding(db, user_id=user_id, run_id=str(request.run_id))
                assert run.status == "cancelled" and run.version == 2
        finally:
            release.set()
        with pytest.raises(ApiError) as conflict:
            future.result(timeout=10)
        assert conflict.value.code == "AGENT_STATE_CONFLICT"
    with Session(engine) as db:
        run = get_run(db, user_id=user_id, run_id=str(request.run_id))
        assert run.status == "cancelled" and run.version == 2
        assert run.state_json["processing"] is False
        assert run.state_json.get("preview") is None and run.error_code is None
        assert db.query(Topic).count() == db.query(StudyPlan).count() == 0
