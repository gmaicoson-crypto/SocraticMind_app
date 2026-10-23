from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from core.errors import ApiError
from models import ChatMessage, ChatSession, ChatTurn, Topic
from services.chat_lifecycle import (
    begin_chat_turn,
    cancel_chat_turn,
    finish_chat_turn,
    refresh_generation_lease,
    utcnow,
)
from services.progress_archive import archive_and_delete_messages


def start(db, user_id, request_id="request-1", **kwargs):
    args = dict(
        user_id=user_id,
        topic_id=None,
        session_id="conversation",
        node_key="normal",
        user_input="question",
        mode="normal",
        request_id=request_id,
        model_id="test-model",
    )
    args.update(kwargs)
    return begin_chat_turn(db, **args)


def complete(db, user_id, request_id="request-1", content="answer", status="complete", token=None):
    turn = db.query(ChatTurn).filter_by(user_id=user_id, request_id=request_id).first()
    return finish_chat_turn(
        db,
        user_id=user_id,
        request_id=request_id,
        content=content,
        status=status,
        generation_token=token or (turn.generation_token if turn else "missing"),
    )


def test_request_replay_and_fingerprint(db_session, auth_user):
    first = start(db_session, auth_user.id)
    replay = start(db_session, auth_user.id)
    assert replay.replayed
    assert replay.turn.id == first.turn.id
    assert db_session.query(ChatMessage).count() == 2
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user.id, user_input="changed")
    assert error.value.code == "CHAT_REQUEST_CONFLICT"
    assert complete(db_session, auth_user.id)
    assert start(db_session, auth_user.id).turn.status == "complete"


def test_session_claim_is_shared_across_db_sessions(db_session, auth_user):
    first = start(db_session, auth_user.id)
    with Session(bind=db_session.get_bind()) as second_db:
        with pytest.raises(ApiError) as error:
            start(second_db, auth_user.id, "other-request")
        assert error.value.code == "CHAT_SESSION_BUSY"
        unrelated = start(second_db, auth_user.id, "other-session-request", session_id="other")
        assert unrelated.turn.status == "generating"
    assert complete(db_session, auth_user.id)
    assert first.turn.id != start(db_session, auth_user.id, "next-request").turn.id


def test_expired_generation_releases_lease_and_rejects_old_writer(db_session, auth_user):
    first = start(db_session, auth_user.id)
    db_session.query(ChatSession).filter_by(id=first.session.id).update(
        {
            "generation_lease_until": utcnow() - timedelta(seconds=1),
        }
    )
    db_session.commit()
    start(db_session, auth_user.id, "next")
    assert not complete(db_session, auth_user.id)
    assert db_session.get(ChatTurn, first.turn.id).status == "interrupted"
    assert complete(db_session, auth_user.id, "next")


def test_lease_refresh_preserves_partial_answer_then_cancel_prevents_completion(
    db_session, auth_user
):
    turn = start(db_session, auth_user.id)
    assert refresh_generation_lease(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        content="partial",
        generation_token=turn.turn.generation_token,
    )
    cancelled = cancel_chat_turn(
        db_session, user_id=auth_user.id, session_id="conversation", request_id="request-1"
    )
    assert cancelled.status == "interrupted"
    assert not complete(db_session, auth_user.id)
    db_session.expire_all()
    assert db_session.get(ChatMessage, turn.ai_message.id).content == "partial"
    assert not refresh_generation_lease(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        generation_token=turn.turn.generation_token,
    )


def test_failed_regeneration_preserves_answer_success_replaces_and_invalidates(
    db_session, auth_user
):
    first = start(db_session, auth_user.id)
    assert complete(db_session, auth_user.id)
    db_session.refresh(first.session)
    first.session.summary_json = {"summary": "old answer"}
    first.session.summary_through_turn_id = first.turn.id
    first.session.summary_source_version = first.session.content_version
    first.session.summary_status = "ready"
    db_session.commit()
    version = first.session.content_version
    start(db_session, auth_user.id, "regen-fail", regenerate_message_id=first.ai_message.id)
    assert complete(db_session, auth_user.id, "regen-fail", status="failed")
    db_session.expire_all()
    assert first.turn.status == "complete"
    assert first.session.summary_json == {"summary": "old answer"}
    replacement = start(
        db_session, auth_user.id, "regen-ok", regenerate_message_id=first.ai_message.id
    )
    assert replacement.user_message.id == first.user_message.id
    assert complete(db_session, auth_user.id, "regen-ok", content="new answer")
    db_session.expire_all()
    assert first.turn.status == "superseded"
    assert first.ai_message.metadata_json["status"] == "superseded"
    assert first.session.content_version == version + 1
    assert first.session.summary_json is None
    assert first.session.summary_status == "pending"
    assert db_session.query(ChatMessage).filter_by(role="user").count() == 1


def test_regenerate_only_latest_question_and_reject_changes(db_session, auth_user):
    first = start(db_session, auth_user.id)
    complete(db_session, auth_user.id)
    with pytest.raises(ApiError):
        start(
            db_session,
            auth_user.id,
            "bad-question",
            user_input="tampered",
            regenerate_message_id=first.ai_message.id,
        )
    start(db_session, auth_user.id, "second", user_input="second question")
    complete(db_session, auth_user.id, "second")
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user.id, "bad-earlier", regenerate_message_id=first.ai_message.id)
    assert error.value.code == "CHAT_REGENERATE_NOT_LATEST"


def test_append_keeps_summary_source_version(db_session, auth_user):
    first = start(db_session, auth_user.id)
    complete(db_session, auth_user.id)
    db_session.refresh(first.session)
    first.session.summary_json = {"summary": "older dialogue"}
    first.session.summary_source_version = first.session.content_version
    db_session.commit()
    start(db_session, auth_user.id, "second")
    complete(db_session, auth_user.id, "second")
    db_session.expire_all()
    assert first.session.content_version == first.session.summary_source_version
    assert first.session.summary_json is not None


def test_delete_invalidates_summary_and_prevents_inflight_completion(db_session, auth_user):
    first = start(db_session, auth_user.id)
    complete(db_session, auth_user.id)
    db_session.refresh(first.session)
    first.session.summary_json = {"summary": "private"}
    first.session.summary_status = "running"
    first.session.summary_lease_token = "old-summary-job"
    db_session.commit()
    second = start(db_session, auth_user.id, "second")
    assert (
        archive_and_delete_messages(db_session, user_id=auth_user.id, ids=[first.ai_message.id])
        == 1
    )
    db_session.commit()
    assert not complete(db_session, auth_user.id, "second")
    db_session.expire_all()
    assert first.session.summary_json is None
    assert first.session.summary_lease_token is None
    assert first.session.content_version > second.turn.source_version
    assert first.turn.status == "deleted"


def test_delete_session_removes_jobs_and_recreated_session_rejects_old_writer(
    db_session, auth_user
):
    first = start(db_session, auth_user.id)
    old_session_id = first.session.id
    archive_and_delete_messages(db_session, user_id=auth_user.id, session_id="conversation")
    db_session.commit()
    db_session.expunge_all()
    assert db_session.query(ChatSession).count() == 0
    assert db_session.query(ChatTurn).count() == 0
    second = start(db_session, auth_user.id, "second")
    assert second.session.id != old_session_id
    assert not complete(db_session, auth_user.id)


def test_delete_empty_topic_session_cleans_context(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="topic")
    db_session.add(topic)
    db_session.flush()
    db_session.add(
        ChatSession(user_id=auth_user.id, session_id="empty", topic_id=topic.id, mode="socratic")
    )
    db_session.commit()
    assert archive_and_delete_messages(db_session, user_id=auth_user.id, topic_id=topic.id) == 0
    db_session.commit()
    assert db_session.query(ChatSession).count() == 0


def test_existing_history_session_scope_cannot_change(db_session, auth_user):
    db_session.add(
        ChatMessage(
            user_id=auth_user.id,
            topic_id=42,
            session_id="conversation",
            node_key="node",
            role="user",
            content="private",
            mode="socratic",
        )
    )
    db_session.commit()
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user.id)
    assert error.value.code == "CHAT_SESSION_SCOPE_CONFLICT"


def test_expired_same_request_replay_returns_interrupted(db_session, auth_user):
    first = start(db_session, auth_user.id)
    db_session.query(ChatSession).filter_by(id=first.session.id).update(
        {
            "generation_lease_until": utcnow() - timedelta(seconds=1),
        }
    )
    db_session.commit()
    replay = start(db_session, auth_user.id)
    assert replay.replayed
    assert replay.turn.status == "interrupted"
    assert not complete(db_session, auth_user.id)


def test_simultaneous_requests_have_one_generation_claim(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from core.database import Base
    from models import User

    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="concurrent", email="concurrent@example.test", hashed_password="hash")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(ChatSession(user_id=user_id, session_id="conversation", mode="normal"))
        db.commit()
    barrier = Barrier(2)

    def attempt(request_id):
        with Session(engine) as db:
            barrier.wait(timeout=5)
            try:
                return start(db, user_id, request_id).turn.status
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ["concurrent-1", "concurrent-2"]))
    assert sorted(results) == ["CHAT_SESSION_BUSY", "generating"]
    with Session(engine) as db:
        assert db.query(ChatTurn).count() == 1
        assert db.query(ChatMessage).count() == 2
    engine.dispose()


def test_deleted_request_id_reuse_cannot_receive_old_stream(db_session, auth_user):
    first = start(db_session, auth_user.id)
    old_token = first.turn.generation_token
    archive_and_delete_messages(db_session, user_id=auth_user.id, session_id="conversation")
    db_session.commit()
    db_session.expunge_all()
    fresh = start(db_session, auth_user.id)
    assert not complete(db_session, auth_user.id, token=old_token)
    assert not refresh_generation_lease(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        generation_token=old_token,
        content="obsolete",
    )
    assert complete(db_session, auth_user.id, token=fresh.turn.generation_token, content="fresh")
    db_session.refresh(fresh.ai_message)
    assert fresh.ai_message.content == "fresh"


def test_cancelled_partial_checkpoint_never_revives_deleted_or_superseded_turn(
    db_session, auth_user
):
    from services.chat_lifecycle import checkpoint_interrupted_content

    first = start(db_session, auth_user.id)
    token = first.turn.generation_token
    cancel_chat_turn(
        db_session, user_id=auth_user.id, session_id="conversation", request_id="request-1"
    )
    assert checkpoint_interrupted_content(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        generation_token=token,
        content="partial",
    )
    assert not complete(db_session, auth_user.id)
    start(db_session, auth_user.id, "regen", regenerate_message_id=first.ai_message.id)
    complete(db_session, auth_user.id, "regen", content="replacement")
    assert not checkpoint_interrupted_content(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        generation_token=token,
        content="partial late",
    )
    archive_and_delete_messages(db_session, user_id=auth_user.id, session_id="conversation")
    db_session.commit()
    assert not checkpoint_interrupted_content(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        generation_token=token,
        content="partial very late",
    )


def test_cancel_before_begin_is_durable_and_prevents_generation(db_session, auth_user):
    from models import ChatCancellation

    assert (
        cancel_chat_turn(
            db_session, user_id=auth_user.id, session_id="conversation", request_id="request-1"
        )
        is None
    )
    assert db_session.query(ChatCancellation).count() == 1
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user.id)
    assert error.value.code == "CHAT_REQUEST_CANCELLED"
    assert db_session.query(ChatMessage).count() == 0
    assert db_session.query(ChatTurn).count() == 0
    archive_and_delete_messages(db_session, user_id=auth_user.id, session_id="conversation")
    db_session.commit()
    assert db_session.query(ChatCancellation).count() == 1
    assert start(db_session, auth_user.id, "fresh-request").turn.status == "generating"


def test_stop_intent_blocks_model_start_and_completion_before_cancel_transition(
    db_session, auth_user
):
    from models import ChatCancellation

    first = start(db_session, auth_user.id)
    db_session.add(
        ChatCancellation(user_id=auth_user.id, session_id="conversation", request_id="request-1")
    )
    db_session.commit()
    assert not refresh_generation_lease(
        db_session,
        user_id=auth_user.id,
        request_id="request-1",
        generation_token=first.turn.generation_token,
    )
    assert not complete(db_session, auth_user.id)
    cancelled = cancel_chat_turn(
        db_session, user_id=auth_user.id, session_id="conversation", request_id="request-1"
    )
    assert cancelled.status == "interrupted"


def test_ai_metadata_retains_question_and_overview_kind(db_session, auth_user):
    first = start(db_session, auth_user.id, kind="topic_overview")
    assert first.ai_message.metadata_json["user_message_id"] == first.user_message.id
    assert first.ai_message.metadata_json["kind"] == "topic_overview"
    assert first.ai_message.metadata_json["node_key"] == "normal"
    assert complete(db_session, auth_user.id)
    assert first.ai_message.metadata_json["kind"] == "topic_overview"


def test_onboarding_without_topic_can_bind_first_chat_to_created_topic(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="New learning topic")
    db_session.add(topic)
    db_session.flush()
    db_session.add(
        ChatMessage(
            user_id=auth_user.id,
            session_id="conversation",
            node_key="",
            role="ai",
            content="Your learning goal?",
            mode="socratic",
            message_type="agent_step",
            topic_id=None,
        )
    )
    db_session.commit()
    first = start(
        db_session,
        auth_user.id,
        topic_id=topic.id,
        mode="socratic",
        kind="topic_overview",
        user_input="",
    )
    assert first.session.topic_id == topic.id
    assert complete(db_session, auth_user.id)
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user.id, "wrong-topic", topic_id=None, mode="socratic")
    assert error.value.code == "CHAT_SESSION_SCOPE_CONFLICT"


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_expired_unclaimed_lease_can_settle_unsuccessful_turn(db_session, auth_user, status):
    first = start(db_session, auth_user.id)
    token = first.turn.generation_token
    db_session.query(ChatSession).filter_by(id=first.session.id).update(
        {"generation_lease_until": utcnow() - timedelta(seconds=1)}
    )
    db_session.commit()
    assert not complete(db_session, auth_user.id, token=token)
    assert complete(
        db_session, auth_user.id, content="partial before timeout", status=status, token=token
    )
    db_session.expire_all()
    assert first.turn.status == status
    assert first.ai_message.metadata_json["status"] == status
    assert first.ai_message.content == "partial before timeout"
    assert first.session.active_request_id is None
    assert first.session.generation_lease_token is None
    assert start(db_session, auth_user.id, "after-timeout").turn.status == "generating"


@pytest.mark.parametrize("changed", ["token", "version", "request"])
def test_expired_failure_cannot_settle_after_ownership_changes(db_session, auth_user, changed):
    first = start(db_session, auth_user.id)
    token = first.turn.generation_token
    updates = {"generation_lease_until": utcnow() - timedelta(seconds=1)}
    if changed == "token":
        updates["generation_lease_token"] = "replacement-token"
    elif changed == "version":
        updates["content_version"] = first.session.content_version + 1
    else:
        updates["active_request_id"] = "replacement-request"
    db_session.query(ChatSession).filter_by(id=first.session.id).update(updates)
    db_session.commit()
    assert not complete(
        db_session, auth_user.id, content="late failure", status="failed", token=token
    )
    db_session.expire_all()
    assert first.ai_message.content == ""
    assert first.ai_message.metadata_json["status"] == "streaming"
    assert first.session.active_request_id == updates.get("active_request_id", "request-1")
    assert first.session.generation_lease_token == updates.get("generation_lease_token", token)


def test_failure_during_cancel_transition_is_recorded_as_interrupted(db_session, auth_user):
    from models import ChatCancellation

    first = start(db_session, auth_user.id)
    db_session.add(
        ChatCancellation(user_id=auth_user.id, session_id="conversation", request_id="request-1")
    )
    db_session.commit()
    assert complete(db_session, auth_user.id, content="partial", status="failed")
    db_session.expire_all()
    assert first.turn.status == "interrupted"
    assert first.turn.error_code == "USER_CANCELLED"
    assert first.ai_message.metadata_json["status"] == "interrupted"
    assert first.session.active_request_id is None
