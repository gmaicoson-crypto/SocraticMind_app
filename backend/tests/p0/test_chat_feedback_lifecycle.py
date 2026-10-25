"""Usage follows existing generation ownership and interruption boundaries."""

import pytest

from models import ChatMessage
from services.chat_lifecycle import (
    cancel_chat_turn,
    checkpoint_interrupted_content,
    finish_chat_turn,
    refresh_generation_lease,
)
from tests.feedback_cases import DATA
from tests.p0.test_chat_lifecycle import start


def test_terminal_turn_cannot_be_overwritten_with_another_usage_report(db_session, auth_user):
    attempt = start(db_session, auth_user.id)
    arguments = dict(
        user_id=auth_user.id,
        request_id=attempt.turn.request_id,
        generation_token=attempt.turn.generation_token,
        content="complete answer",
        status="complete",
    )
    assert finish_chat_turn(db_session, **arguments, usage=DATA["reported_usage"])
    assert not finish_chat_turn(db_session, **arguments, usage=DATA["zero_usage"])
    db_session.expire_all()
    assert (
        db_session.get(ChatMessage, attempt.ai_message.id).metadata_json["usage"]
        == DATA["reported_usage"]
    )


@pytest.mark.parametrize(
    "stale", [None, "token", "account", "version", "new_turn", "new_turn_complete", "shorter"]
)
def test_cancelled_checkpoint_can_add_usage_without_reviving_or_overwriting_new_work(
    db_session, auth_user, stale
):
    attempt = start(db_session, auth_user.id)
    arguments = dict(
        user_id=auth_user.id,
        request_id=attempt.turn.request_id,
        generation_token=attempt.turn.generation_token,
        content="partial answer",
    )
    assert refresh_generation_lease(db_session, **arguments)
    cancel_chat_turn(
        db_session,
        user_id=auth_user.id,
        session_id="conversation",
        request_id=attempt.turn.request_id,
    )
    if stale == "token":
        arguments["generation_token"] = "stale-token"
    elif stale == "account":
        arguments["user_id"] = auth_user.id + 1
    elif stale == "version":
        attempt.session.content_version += 1
        db_session.commit()
    elif stale in {"new_turn", "new_turn_complete"}:
        latest = start(db_session, auth_user.id, "new-request")
        if stale == "new_turn_complete":
            assert finish_chat_turn(
                db_session,
                user_id=auth_user.id,
                request_id=latest.turn.request_id,
                generation_token=latest.turn.generation_token,
                content="new answer",
                status="complete",
                usage=DATA["zero_usage"],
            )
    elif stale == "shorter":
        arguments["content"] = "partial"
    accepted = checkpoint_interrupted_content(db_session, **arguments, usage=DATA["reported_usage"])
    assert accepted is (stale is None)
    db_session.expire_all()
    message = db_session.get(ChatMessage, attempt.ai_message.id)
    assert message.content == "partial answer" and message.metadata_json["status"] == "interrupted"
    assert message.metadata_json.get("usage") == (DATA["reported_usage"] if accepted else None)
    assert not checkpoint_interrupted_content(db_session, **arguments, usage=DATA["reported_usage"])
