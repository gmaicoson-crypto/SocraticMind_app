import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from core import ai_client
from core.config import LLMProfile
from core.context_budget import (
    ContextWindowExceeded,
    count_messages,
    ensure_fits,
    get_context_policy,
)
from models import ChatMessage, ChatSession, ChatTurn, Topic, User
from services import chat_summaries
from services.chat_context import iter_history_blocks, valid_summary
from services.chat_lifecycle import begin_chat_turn, finish_chat_turn
from services.chat_summaries import (
    MAX_ATTEMPTS,
    SessionSummary,
    run_one_summary_job,
    schedule_chat_summary,
)
from services.progress_archive import archive_and_delete_messages


@pytest.fixture
def summary_environment(db_session, monkeypatch):
    profile = LLMProfile(
        id="summary-test",
        name="Summary test",
        model="unknown-summary-model",
        api_key="test-key",
        base_url="https://example.test/v1",
    )
    monkeypatch.setattr(ai_client, "resolve_llm_profile", lambda *_args, **_kwargs: profile)
    monkeypatch.setattr("core.context_budget.resolve_llm_profile", lambda *_args: profile)
    created_sessions = []

    def factory():
        db = Session(bind=db_session.get_bind(), expire_on_commit=False)
        created_sessions.append(db)
        return db

    return SimpleNamespace(factory=factory, profile=profile, sessions=created_sessions)


def add_session(db, user, *, session_id=None, topic_id=None, status="pending"):
    session = ChatSession(
        user_id=user.id,
        session_id=session_id or str(uuid.uuid4()),
        topic_id=topic_id,
        mode="socratic" if topic_id else "normal",
        summary_status=status,
        summary_model="summary-test",
    )
    db.add(session)
    db.flush()
    return session


def add_turns(db, session, count=6, *, characters=10_000, node_key="normal"):
    turns = []
    for index in range(count):
        args = dict(
            user_id=session.user_id,
            session_id=session.session_id,
            topic_id=session.topic_id,
            node_key=node_key,
            mode=session.mode,
            message_type="chat",
            metadata_json={"status": "complete"},
        )
        user = ChatMessage(**args, role="user", content=f"question {index}")
        answer = ChatMessage(**args, role="ai", content=f"answer {index} " + "x" * characters)
        db.add_all([user, answer])
        db.flush()
        turn = ChatTurn(
            chat_session_id=session.id,
            user_id=session.user_id,
            request_id=str(uuid.uuid4()),
            request_fingerprint="test",
            user_message_id=user.id,
            ai_message_id=answer.id,
            status="complete",
            model_id="summary-test",
            node_key=node_key,
            generation_token=str(uuid.uuid4()),
            source_version=session.content_version,
        )
        db.add(turn)
        db.flush()
        turns.append(turn)
    db.commit()
    return turns


def summary_result(messages, *, goal="学习递归", **overrides):
    payload = json.loads(messages[-1]["content"])
    previous = payload.get("previous_summary") or {}
    ids = list(previous.get("source_message_ids", []))
    nodes = list(previous.get("node_keys", []))
    for turn in payload["turns"]:
        ids.extend(turn["message_ids"])
        nodes.append(turn["node_key"])
    data = {
        "goal": goal,
        "conclusions": ["讨论了函数的调用"],
        "unresolved": ["还需验证边界情况"],
        "source_message_ids": list(dict.fromkeys(ids))[-128:],
        "node_keys": list(dict.fromkeys(nodes)),
        **overrides,
    }
    return SimpleNamespace(value=SessionSummary.model_validate(data), token_usage=321)


@pytest.mark.parametrize("characters", [3_000, 10_000])
def test_short_conversation_stays_verbatim_without_summary_call(
    db_session,
    auth_user,
    summary_environment,
    characters,
):
    session = add_session(db_session, auth_user)
    turns = add_turns(db_session, session, count=4, characters=characters)

    def unexpected(*_args):
        pytest.fail("A short conversation should not call the summary model")

    assert run_one_summary_job(summary_environment.factory, unexpected)
    db_session.refresh(session)
    assert session.summary_status == "ready"
    assert session.summary_json is None
    assert len(list(iter_history_blocks(db_session, session))) == len(turns)


def test_summary_retains_recent_whole_turns_checks_budget_and_releases_transaction(
    db_session,
    auth_user,
    summary_environment,
    monkeypatch,
):
    session = add_session(db_session, auth_user)
    turns = add_turns(db_session, session)
    original_content = {row.id: row.content for row in db_session.query(ChatMessage)}
    checked = []
    captured = []

    def verify(messages, model_id):
        checked.append(messages)
        return ensure_fits(messages, model_id)

    def generate(schema, messages, context):
        assert schema is SessionSummary
        assert context.model == "summary-test"
        assert checked[-1] == messages
        assert not any(db.in_transaction() for db in summary_environment.sessions)
        captured.append(json.loads(messages[-1]["content"]))
        return summary_result(messages)

    monkeypatch.setattr(chat_summaries, "ensure_fits", verify)
    assert run_one_summary_job(summary_environment.factory, generate)
    db_session.refresh(session)
    assert valid_summary(session)
    assert session.summary_through_turn_id == turns[3].id
    assert session.summary_source_version == session.content_version
    assert session.summary_version == 2
    assert session.summary_json["schema_version"] == 1
    assert [turn["message_ids"] for turn in captured[0]["turns"]] == [
        [turn.user_message_id, turn.ai_message_id] for turn in turns[:4]
    ]
    tail = list(
        iter_history_blocks(db_session, session, after_turn_id=session.summary_through_turn_id)
    )
    assert [block.turn_id for block in tail] == [turn.id for turn in reversed(turns[4:])]
    saved_summary_tokens = count_messages(
        [{"role": "user", "content": json.dumps(session.summary_json, ensure_ascii=False)}],
        "summary-test",
    )
    assert saved_summary_tokens <= 4_000
    assert (
        saved_summary_tokens
        + count_messages([message for block in tail for message in block.messages], "summary-test")
        <= 32_000
    )
    assert {row.id: row.content for row in db_session.query(ChatMessage)} == original_content


def test_large_conversation_is_summarized_in_bounded_chunks_with_monotonic_cursor(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    turns = add_turns(db_session, session, count=22)
    summarized_ids = []
    previous_sources = []
    cursors = []
    calls = []

    def generate(_schema, messages, _context):
        assert (
            count_messages(messages, "summary-test")
            <= get_context_policy("summary-test").target_input_tokens
        )
        payload = json.loads(messages[-1]["content"])
        if calls:
            assert payload["previous_summary"]["source_message_ids"] == previous_sources
        calls.append(messages)
        for turn in payload["turns"]:
            summarized_ids.extend(turn["message_ids"])
        result = summary_result(messages)
        previous_sources[:] = result.value.source_message_ids
        return result

    for _ in range(10):
        if not run_one_summary_job(summary_environment.factory, generate):
            break
        db_session.refresh(session)
        cursors.append(session.summary_through_turn_id)
    else:
        pytest.fail("Summary cursor did not reach a stable retained tail")
    assert len(calls) > 1
    assert cursors == sorted(cursors)
    assert len(summarized_ids) == len(set(summarized_ids))
    assert summarized_ids == [
        message_id
        for turn in turns[:-2]
        for message_id in (turn.user_message_id, turn.ai_message_id)
    ]
    assert session.summary_through_turn_id == turns[-3].id
    assert session.summary_status == "ready"
    assert session.summary_lease_token is None


def test_failed_jobs_back_off_stop_after_three_attempts_and_new_turn_can_reschedule(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session)
    calls = []

    def failing(*_args):
        calls.append(True)
        raise RuntimeError("provider temporarily unavailable")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        assert run_one_summary_job(summary_environment.factory, failing)
        db_session.refresh(session)
        assert session.summary_attempts == attempt
        assert session.summary_status == "failed"
        assert session.summary_next_retry_at.replace(tzinfo=timezone.utc) > datetime.now(
            timezone.utc
        )
        assert not run_one_summary_job(summary_environment.factory, failing)
        session.summary_next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
    assert not run_one_summary_job(summary_environment.factory, failing)
    assert len(calls) == MAX_ATTEMPTS
    schedule_chat_summary(db_session, session_id=session.id, model_id="summary-test")
    db_session.refresh(session)
    assert session.summary_status == "pending"
    assert session.summary_attempts == 0
    assert session.summary_next_retry_at is None


def test_running_job_waits_for_lease_and_recovers_after_process_restart(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user, status="running")
    add_turns(db_session, session)
    session.summary_attempts = 1
    session.summary_lease_token = "terminated-process"
    session.summary_lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    db_session.commit()

    def generate(_schema, messages, _context):
        return summary_result(messages)

    assert not run_one_summary_job(summary_environment.factory, generate)
    session.summary_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert run_one_summary_job(summary_environment.factory, generate)
    db_session.refresh(session)
    assert valid_summary(session)
    assert session.summary_lease_token is None


def test_repeated_process_crashes_exhaust_durable_retry_limit(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user, status="running")
    add_turns(db_session, session)
    session.summary_attempts = MAX_ATTEMPTS
    session.summary_lease_token = "crashed-again"
    session.summary_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert not run_one_summary_job(
        summary_environment.factory, lambda *_: pytest.fail("attempt limit exceeded")
    )
    db_session.refresh(session)
    assert session.summary_status == "failed"
    assert session.summary_lease_token is None
    assert session.summary_attempts == MAX_ATTEMPTS


def test_expired_worker_cannot_overwrite_reclaimed_workers_summary(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session)
    session_id = session.id

    def stale_generator(_schema, messages, _context):
        with summary_environment.factory() as db:
            db.query(ChatSession).filter_by(id=session_id).update(
                {"summary_lease_until": datetime.now(timezone.utc) - timedelta(seconds=1)}
            )
            db.commit()
        assert run_one_summary_job(
            summary_environment.factory,
            lambda _schema, msgs, _context: summary_result(msgs, goal="新工作进程结果"),
        )
        return summary_result(messages, goal="旧工作进程结果")

    assert run_one_summary_job(summary_environment.factory, stale_generator)
    db_session.refresh(session)
    assert session.summary_json["goal"] == "新工作进程结果"
    assert session.summary_version == 2


@pytest.mark.parametrize("mutation", ["delete_message", "delete_session", "regenerate"])
def test_concurrent_deletion_or_regeneration_rejects_stale_summary(
    db_session,
    auth_user,
    summary_environment,
    mutation,
):
    session = add_session(db_session, auth_user)
    turns = add_turns(db_session, session)
    session_id, name, user_id = session.id, session.session_id, auth_user.id
    version = session.content_version
    old_ai_id = turns[0].ai_message_id
    last_ai_id = turns[-1].ai_message_id
    last_question = db_session.get(ChatMessage, turns[-1].user_message_id).content

    def generate(_schema, messages, _context):
        with summary_environment.factory() as db:
            if mutation == "delete_session":
                archive_and_delete_messages(db, user_id=user_id, session_id=name)
                db.commit()
            elif mutation == "delete_message":
                archive_and_delete_messages(db, user_id=user_id, ids=[old_ai_id])
                db.commit()
            else:
                replacement = begin_chat_turn(
                    db,
                    user_id=user_id,
                    topic_id=None,
                    session_id=name,
                    node_key="normal",
                    user_input=last_question,
                    mode="normal",
                    request_id="replacement",
                    model_id="summary-test",
                    regenerate_message_id=last_ai_id,
                )
                assert finish_chat_turn(
                    db,
                    user_id=user_id,
                    request_id="replacement",
                    content="new answer",
                    status="complete",
                    generation_token=replacement.turn.generation_token,
                )
        return summary_result(messages, goal="已失效内容")

    assert run_one_summary_job(summary_environment.factory, generate)
    db_session.expire_all()
    saved = db_session.get(ChatSession, session_id)
    if mutation == "delete_session":
        assert saved is None
    else:
        assert saved.content_version == version + 1
        assert saved.summary_json is None
        assert saved.summary_lease_token is None
        assert saved.summary_status == "pending"


@pytest.mark.parametrize(
    "invalid", [{"source_message_ids": [987654321]}, {"node_keys": ["foreign-node"]}]
)
def test_unknown_summary_sources_are_rejected_and_previous_summary_survives(
    db_session,
    auth_user,
    summary_environment,
    invalid,
):
    session = add_session(db_session, auth_user)
    turns = add_turns(db_session, session)
    old_summary = {
        "goal": "可靠的旧摘要",
        "node_keys": ["normal"],
        "source_message_ids": [turns[0].user_message_id, turns[0].ai_message_id],
    }
    session.summary_json = old_summary
    session.summary_through_turn_id = turns[0].id
    session.summary_source_version = session.content_version
    db_session.commit()
    assert run_one_summary_job(
        summary_environment.factory,
        lambda _schema, messages, _context: summary_result(messages, **invalid),
    )
    db_session.refresh(session)
    assert session.summary_status == "failed"
    assert session.summary_json == old_summary
    assert session.summary_through_turn_id == turns[0].id
    assert session.summary_version == 1


def test_summary_input_is_isolated_by_user_topic_and_session(
    db_session,
    auth_user,
    summary_environment,
):
    other = User(
        username="summary-other", email="summary-other@example.test", hashed_password="unused"
    )
    db_session.add(other)
    topics = [Topic(user_id=auth_user.id, title="A"), Topic(user_id=auth_user.id, title="B")]
    db_session.add_all(topics)
    db_session.flush()
    main = add_session(db_session, auth_user, session_id="shared-name", topic_id=topics[0].id)
    ours = add_turns(db_session, main, node_key="same-node")
    other_user = add_session(db_session, other, session_id="shared-name", status="idle")
    other_topic = add_session(db_session, auth_user, topic_id=topics[1].id, status="idle")
    other_session = add_session(db_session, auth_user, topic_id=topics[0].id, status="idle")
    foreign_turns = []
    for item in [other_user, other_topic, other_session]:
        foreign_turns += add_turns(db_session, item, node_key="same-node")
    captured = []

    def generate(_schema, messages, _context):
        captured.extend(
            message_id
            for turn in json.loads(messages[-1]["content"])["turns"]
            for message_id in turn["message_ids"]
        )
        return summary_result(messages)

    assert run_one_summary_job(summary_environment.factory, generate)
    own_ids = {
        message_id for turn in ours for message_id in (turn.user_message_id, turn.ai_message_id)
    }
    foreign_ids = {
        message_id
        for turn in foreign_turns
        for message_id in (turn.user_message_id, turn.ai_message_id)
    }
    assert captured and set(captured).issubset(own_ids)
    assert not set(captured) & foreign_ids
    db_session.refresh(main)
    assert set(main.summary_json["source_message_ids"]).issubset(own_ids)


def test_summary_request_over_hard_limit_never_calls_provider_or_marks_ready(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session, count=1, characters=260_000)
    add_turns(db_session, session, count=3)
    assert run_one_summary_job(
        summary_environment.factory, lambda *_: pytest.fail("oversized request sent to provider")
    )
    db_session.refresh(session)
    assert session.summary_status == "failed"
    assert session.summary_json is None
    assert session.summary_attempts == 1


def test_final_summary_budget_guard_runs_before_provider(
    db_session,
    auth_user,
    summary_environment,
    monkeypatch,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session)
    checked = []

    def reject(messages, _model_id):
        checked.append(messages)
        raise ContextWindowExceeded(20, 10)

    monkeypatch.setattr(chat_summaries, "ensure_fits", reject)
    assert run_one_summary_job(
        summary_environment.factory, lambda *_: pytest.fail("guard was bypassed")
    )
    db_session.refresh(session)
    assert checked
    assert session.summary_status == "failed"


def test_verbose_summary_is_rejected_before_replacing_context(
    db_session,
    auth_user,
    summary_environment,
):
    summary_environment.profile.summary_target_tokens = 500
    session = add_session(db_session, auth_user)
    add_turns(db_session, session)
    assert run_one_summary_job(
        summary_environment.factory,
        lambda _schema, messages, _context: summary_result(messages, goal="长" * 600),
    )
    db_session.refresh(session)
    assert session.summary_status == "failed"
    assert session.summary_json is None
    assert session.summary_through_turn_id is None


@pytest.mark.parametrize("foreign_scope", ["user", "topic", "session"])
def test_broken_cross_scope_turn_links_cannot_leak_into_summary_sources(
    db_session,
    auth_user,
    summary_environment,
    foreign_scope,
):
    other = User(
        username="source-other", email="source-other@example.test", hashed_password="unused"
    )
    db_session.add(other)
    topic = Topic(user_id=auth_user.id, title="Private topic")
    db_session.add(topic)
    db_session.flush()
    main = add_session(db_session, auth_user)
    ours = add_turns(db_session, main)
    foreign = add_session(
        db_session,
        other if foreign_scope == "user" else auth_user,
        topic_id=topic.id if foreign_scope == "topic" else None,
        status="idle",
    )
    foreign_turn = add_turns(db_session, foreign, count=1)[0]
    # Simulate a damaged relation without granting the foreign messages access.
    foreign_turn.chat_session_id = main.id
    foreign_turn.user_id = auth_user.id
    db_session.commit()
    captured = []

    def generate(_schema, messages, _context):
        captured.extend(
            message_id
            for turn in json.loads(messages[-1]["content"])["turns"]
            for message_id in turn["message_ids"]
        )
        return summary_result(messages)

    assert run_one_summary_job(summary_environment.factory, generate)
    assert captured
    assert foreign_turn.user_message_id not in captured
    assert foreign_turn.ai_message_id not in captured
    assert set(captured).issubset(
        {message_id for turn in ours for message_id in (turn.user_message_id, turn.ai_message_id)}
    )


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_scheduling_queued_work_updates_model_without_resetting_backoff(
    db_session,
    auth_user,
    status,
):
    session = add_session(db_session, auth_user, status=status)
    session.summary_model = "old-model"
    session.summary_attempts = 1
    session.summary_next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    session.summary_lease_token = "existing-marker"
    db_session.commit()
    db_session.refresh(session)
    retry_at = session.summary_next_retry_at
    schedule_chat_summary(db_session, session_id=session.id, model_id="new-model")
    db_session.refresh(session)
    assert session.summary_model == "new-model"
    assert session.summary_attempts == 1
    assert session.summary_next_retry_at == retry_at
    assert session.summary_status == status
    assert session.summary_lease_token == "existing-marker"


def test_scheduling_running_work_keeps_claimed_model_snapshot(db_session, auth_user):
    session = add_session(db_session, auth_user, status="running")
    session.summary_model = "claimed-model"
    session.summary_attempts = 1
    session.summary_lease_token = "active-lease"
    db_session.commit()
    schedule_chat_summary(db_session, session_id=session.id, model_id="new-model")
    db_session.refresh(session)
    assert session.summary_model == "claimed-model"
    assert session.summary_status == "running"
    assert session.summary_lease_token == "active-lease"


def test_summary_without_model_does_not_fall_back_to_global_profile(
    db_session,
    auth_user,
    summary_environment,
    monkeypatch,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session)
    session.summary_model = None
    db_session.commit()
    monkeypatch.setattr(
        chat_summaries, "get_context_policy", lambda *_: pytest.fail("default model fallback")
    )
    assert run_one_summary_job(
        summary_environment.factory, lambda *_: pytest.fail("missing model reached provider")
    )
    db_session.refresh(session)
    assert session.summary_status == "failed"
    assert session.summary_json is None


def test_targeted_job_does_not_claim_or_reap_other_sessions(
    db_session, auth_user, summary_environment
):
    other = add_session(db_session, auth_user)
    add_turns(db_session, other)
    crashed = add_session(db_session, auth_user, status="running")
    crashed.summary_attempts = MAX_ATTEMPTS
    crashed.summary_lease_token = "unrelated-expired-lease"
    crashed.summary_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    target = add_session(db_session, auth_user)
    target_turns = add_turns(db_session, target)
    captured = []

    def generate(_schema, messages, context):
        captured.append(context.run_id)
        ids = {
            message_id
            for item in json.loads(messages[-1]["content"])["turns"]
            for message_id in item["message_ids"]
        }
        assert ids.issubset(
            {
                message_id
                for turn in target_turns
                for message_id in (turn.user_message_id, turn.ai_message_id)
            }
        )
        return summary_result(messages)

    assert run_one_summary_job(summary_environment.factory, generate, target_session_id=target.id)
    db_session.expire_all()
    assert captured == [f"chat-summary:{target.id}:1:1"]
    assert valid_summary(target)
    assert other.summary_status == "pending"
    assert other.summary_attempts == 0
    assert other.summary_json is None
    assert crashed.summary_status == "running"
    assert crashed.summary_lease_token == "unrelated-expired-lease"
    assert not run_one_summary_job(
        summary_environment.factory, generate, target_session_id=987654321
    )


def test_forced_job_below_threshold_preserves_latest_complete_turn_verbatim(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    turns = add_turns(db_session, session, count=3, characters=3_000)
    last_answer = db_session.get(ChatMessage, turns[-1].ai_message_id).content
    captured = []

    def generate(_schema, messages, _context):
        captured.extend(
            turn["message_ids"] for turn in json.loads(messages[-1]["content"])["turns"]
        )
        return summary_result(messages)

    assert run_one_summary_job(
        summary_environment.factory, generate, target_session_id=session.id, force=True
    )
    db_session.refresh(session)
    assert captured == [[turn.user_message_id, turn.ai_message_id] for turn in turns[:-1]]
    assert session.summary_through_turn_id == turns[-2].id
    tail = list(
        iter_history_blocks(db_session, session, after_turn_id=session.summary_through_turn_id)
    )
    assert len(tail) == 1
    assert tail[0].turn_id == turns[-1].id
    assert tail[0].messages[-1]["content"] == last_answer


@pytest.mark.parametrize("state", ["running", "failed", "exhausted"])
def test_force_does_not_bypass_live_lease_backoff_or_attempt_limit(
    db_session,
    auth_user,
    summary_environment,
    state,
):
    session = add_session(
        db_session, auth_user, status="running" if state == "running" else "failed"
    )
    add_turns(db_session, session)
    session.summary_attempts = MAX_ATTEMPTS if state == "exhausted" else 1
    if state == "running":
        session.summary_lease_token = "active-worker"
        session.summary_lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    elif state == "failed":
        session.summary_next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    db_session.commit()
    old_attempts = session.summary_attempts
    assert not run_one_summary_job(
        summary_environment.factory,
        lambda *_: pytest.fail("force bypassed claim constraints"),
        target_session_id=session.id,
        force=True,
    )
    db_session.refresh(session)
    assert session.summary_attempts == old_attempts
    assert session.summary_json is None
    if state == "running":
        assert session.summary_lease_token == "active-worker"


def test_force_rejects_summary_that_is_not_shorter_and_keeps_source_messages(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session, count=2, characters=0)
    original = {message.id: message.content for message in db_session.query(ChatMessage)}
    assert run_one_summary_job(
        summary_environment.factory,
        lambda _schema, messages, _context: summary_result(messages, goal="冗长摘要" * 100),
        target_session_id=session.id,
        force=True,
    )
    db_session.refresh(session)
    assert session.summary_status == "failed"
    assert session.summary_json is None
    assert session.summary_next_retry_at is not None
    assert {message.id: message.content for message in db_session.query(ChatMessage)} == original


def test_summary_json_cap_includes_provenance_and_is_separate_from_32k_target(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    add_turns(db_session, session)

    def generate(_schema, messages, _context):
        return summary_result(messages, conclusions=["长" * 500] * 3)

    assert run_one_summary_job(summary_environment.factory, generate)
    db_session.refresh(session)
    # This valid schema is under 32K but exceeds the independent 4K summary cap.
    assert session.summary_status == "failed"
    assert session.summary_json is None


def test_oversized_latest_turn_remains_verbatim_despite_soft_target(
    db_session,
    auth_user,
    summary_environment,
):
    session = add_session(db_session, auth_user)
    old = add_turns(db_session, session, count=1, characters=3_000)[0]
    latest = add_turns(db_session, session, count=1, characters=50_000)[0]
    assert run_one_summary_job(
        summary_environment.factory, lambda _schema, messages, _context: summary_result(messages)
    )
    db_session.refresh(session)
    assert session.summary_through_turn_id == old.id
    tail = list(
        iter_history_blocks(db_session, session, after_turn_id=session.summary_through_turn_id)
    )
    assert [block.turn_id for block in tail] == [latest.id]
    assert len(tail[0].messages[-1]["content"]) > 50_000


def test_attachment_provenance_is_server_computed_and_blocks_cross_session_context(
    db_session,
    auth_user,
    summary_environment,
):
    from services.chat_context import topic_context_notes

    topic = Topic(user_id=auth_user.id, title="Shared topic")
    db_session.add(topic)
    db_session.flush()
    source = add_session(db_session, auth_user, topic_id=topic.id)
    turns = add_turns(db_session, source, node_key="related-node")
    first_answer = db_session.get(ChatMessage, turns[0].ai_message_id)
    first_answer.metadata_json = {"status": "complete", "attachment_derived": True}
    db_session.commit()
    assert run_one_summary_job(
        summary_environment.factory,
        lambda _schema, messages, _ctx: summary_result(messages, goal="PRIVATE ATTACHMENT RESULT"),
    )
    db_session.refresh(source)
    assert source.summary_json["attachment_derived"] is True
    current = add_session(db_session, auth_user, topic_id=topic.id, status="idle")
    db_session.commit()
    notes = topic_context_notes(db_session, current, node_key="related-node")
    assert "PRIVATE ATTACHMENT RESULT" not in json.dumps(notes)

    # Removing direct flags from later blocks must not erase previous provenance.
    first_answer.metadata_json = {"status": "complete"}
    db_session.commit()
    assert run_one_summary_job(
        summary_environment.factory,
        lambda _schema, messages, _ctx: summary_result(messages),
        target_session_id=source.id,
        force=True,
    )
    db_session.refresh(source)
    assert source.summary_json["attachment_derived"] is True
