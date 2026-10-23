from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from core.deps import get_current_user
from models import AgentRun, ChatMessage, ChatSessionTitle, Topic, User
from services.chat_context import sync_agent_run_message
from services.chat_titles import MAX_ATTEMPTS, SessionTitle, run_one_title_job


def request(client, session_id="session-a", **overrides):
    return client.post(
        "/api/chat/session-titles",
        json={
            "session_id": session_id,
            "mode": "normal",
            "message": "为什么递归需要终止条件？",
            **overrides,
        },
    )


def titles(client, *ids):
    return client.get("/api/chat/session-titles", params=[("ids", value) for value in ids]).json()


def factory(db_session):
    return lambda: Session(bind=db_session.get_bind(), expire_on_commit=False)


@pytest.mark.parametrize("mode", ["socratic", "normal"])
def test_first_message_queues_once_and_returns_server_title(client, db_session, mode):
    first = request(client, mode=mode)
    assert first.status_code == 200
    assert first.json() == {
        "session_id": "session-a",
        "title": None,
        "status": "pending",
        "retry_pending": False,
    }
    assert request(client, mode=mode, message="第二个问题").json() == first.json()
    row = db_session.query(ChatSessionTitle).one()
    assert row.source_text == "为什么递归需要终止条件？"
    calls = []

    def generate(schema, messages, context, **kwargs):
        calls.append((messages, context, kwargs))
        return SimpleNamespace(value=schema(title="递归终止条件"))

    assert run_one_title_job(factory(db_session), generator=generate)
    assert not run_one_title_job(factory(db_session), generator=generate)
    assert len(calls) == 1
    assert calls[0][1].call_type == "chat_title"
    assert calls[0][2]["timeout"] == 20
    db_session.expire_all()
    assert titles(client, "session-a")[0]["title"] == "递归终止条件"
    assert request(client, mode=mode).json()["status"] == "ready"
    assert db_session.query(ChatSessionTitle).one().source_text is None


def test_no_message_does_not_create_title_but_attachment_only_send_does(client, db_session):
    assert request(client, message="  ").status_code == 400
    assert db_session.query(ChatSessionTitle).count() == 0
    assert titles(client, "unused") == []
    assert request(client, message="", attachment_names=["线性代数讲义.pdf"]).status_code == 200
    assert "线性代数讲义.pdf" in db_session.query(ChatSessionTitle).one().source_text
    assert request(client, mode="socratic").status_code == 409
    assert request(client, session_id=" ").status_code == 422


def test_titles_and_renames_are_scoped_to_user(client, app, db_session, auth_user):
    request(client)
    renamed = client.put("/api/chat/session-titles/session-a", json={"title": "  我的递归笔记  "})
    assert renamed.json()["title"] == "我的递归笔记"
    assert renamed.json()["status"] == "manual"
    other = User(username="title-other", email="title-other@example.test", hashed_password="hash")
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    assert titles(client, "session-a") == []
    assert (
        client.put("/api/chat/session-titles/session-a", json={"title": "别人的标题"}).status_code
        == 404
    )
    assert request(client).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: auth_user
    assert titles(client, "session-a")[0]["title"] == "我的递归笔记"
    assert client.put("/api/chat/session-titles/session-a", json={"title": " "}).status_code == 422
    assert (
        client.put("/api/chat/session-titles/session-a", json={"title": "字" * 41}).status_code
        == 422
    )


@pytest.mark.parametrize("action", ["rename", "delete"])
def test_late_generation_cannot_overwrite_rename_or_resurrect_deleted_session(
    client, db_session, action
):
    request(client)

    def generate(schema, *_args, **_kwargs):
        if action == "rename":
            assert (
                client.put(
                    "/api/chat/session-titles/session-a", json={"title": "手动标题"}
                ).status_code
                == 200
            )
        else:
            assert (
                client.request(
                    "DELETE", "/api/chat/session", json={"session_id": "session-a"}
                ).status_code
                == 200
            )
        return SimpleNamespace(value=schema(title="迟到的AI标题"))

    assert run_one_title_job(factory(db_session), generator=generate)
    db_session.expire_all()
    if action == "rename":
        assert titles(client, "session-a")[0]["title"] == "手动标题"
        assert not run_one_title_job(factory(db_session), generator=generate)
    else:
        assert titles(client, "session-a") == []


def test_failure_has_bounded_retries_and_expired_lease_can_be_recovered(client, db_session):
    request(client)
    start = datetime.now(timezone.utc)
    row = db_session.query(ChatSessionTitle).one()
    row.status = "running"
    row.lease_token = "crashed-worker"
    row.lease_until = start - timedelta(seconds=1)
    db_session.commit()
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise TimeoutError()

    assert run_one_title_job(factory(db_session), generator=fail, now=start)
    assert not run_one_title_job(
        factory(db_session), generator=fail, now=start + timedelta(seconds=1)
    )
    for index in range(1, MAX_ATTEMPTS):
        assert run_one_title_job(
            factory(db_session), generator=fail, now=start + timedelta(minutes=index)
        )
    assert not run_one_title_job(
        factory(db_session), generator=fail, now=start + timedelta(minutes=10)
    )
    assert len(calls) == MAX_ATTEMPTS
    db_session.expire_all()
    state = titles(client, "session-a")[0]
    assert state["status"] == "failed"
    assert state["retry_pending"] is False
    assert state["title"] is None
    assert (
        client.put("/api/chat/session-titles/session-a", json={"title": "恢复笔记"}).status_code
        == 200
    )


def test_output_title_is_validated_and_normalized():
    assert SessionTitle(title=" “递归\n终止条件” ").title == "递归 终止条件"
    with pytest.raises(ValueError):
        SessionTitle(title=" ")
    with pytest.raises(ValueError):
        SessionTitle(title="字" * 41)


def test_chat_stream_schedules_without_frontend_title_request_and_skips_overviews(
    client, db_session, auth_user, monkeypatch
):
    import uuid

    monkeypatch.setattr("routers.chat.chat_stream", lambda **_kwargs: iter(["回答"]))
    payload = {
        "node_key": "normal",
        "topic_id": 0,
        "session_id": "streamed",
        "mode": "normal",
        "user_input": "为什么递归需要终止条件？",
        "request_id": str(uuid.uuid4()),
    }
    assert client.post("/api/chat/stream", json=payload).status_code == 200
    row = db_session.query(ChatSessionTitle).one()
    assert row.session_id == "streamed"
    assert row.source_text == payload["user_input"]
    topic = Topic(user_id=auth_user.id, title="递归")
    db_session.add(topic)
    db_session.commit()
    payload.update(
        session_id="automatic",
        kind="topic_overview",
        mode="socratic",
        topic_id=topic.id,
        node_key=topic.title,
        user_input="",
        request_id=str(uuid.uuid4()),
    )
    assert client.post("/api/chat/stream", json=payload).status_code == 200
    assert db_session.query(ChatSessionTitle).count() == 1


def test_learning_agent_answer_schedules_title_but_ai_steps_do_not(db_session, auth_user):
    run = AgentRun(
        user_id=auth_user.id,
        session_id="learning",
        run_type="onboarding",
        status="diagnosing",
        model="default",
        state_json={},
    )
    db_session.add(run)
    db_session.commit()
    payload = {"type": "onboarding", "status": "diagnosing", "step": {"prompt": "诊断问题"}}
    sync_agent_run_message(db_session, run=run, payload=payload)
    assert db_session.query(ChatSessionTitle).count() == 0
    sync_agent_run_message(
        db_session,
        run=run,
        payload=payload,
        answer={"answer": "我的学习回答", "step_id": "q1", "version": 1},
    )
    row = db_session.query(ChatSessionTitle).one()
    assert row.mode == "socratic"
    assert row.source_text == "我的学习回答"


def test_deleting_topic_removes_its_titles_but_preserves_other_sessions(
    client, db_session, auth_user
):
    topic = Topic(user_id=auth_user.id, title="递归")
    db_session.add(topic)
    db_session.flush()
    db_session.add(
        ChatMessage(
            user_id=auth_user.id,
            topic_id=topic.id,
            session_id="topic-chat",
            node_key="root",
            role="user",
            content="学习递归",
            mode="socratic",
        )
    )
    db_session.commit()
    request(client, session_id="topic-chat", mode="socratic")
    request(client, session_id="other-chat")
    assert client.delete(f"/api/topics/{topic.id}").status_code == 200
    assert titles(client, "topic-chat", "other-chat")[0]["session_id"] == "other-chat"
