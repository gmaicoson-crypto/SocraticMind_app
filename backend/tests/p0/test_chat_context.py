import json
import uuid

from models import ChatMessage, LearnerMemory, Node, Topic, User


def create_chat_node(db_session, user, *, title="Chat topic", key="chat-node"):
    topic = Topic(user_id=user.id, title=title)
    db_session.add(topic)
    db_session.flush()
    node = Node(
        topic_id=topic.id,
        node_key=key,
        label="Chat Node",
        state="available",
        parent_keys="",
    )
    db_session.add(node)
    db_session.commit()
    return topic, node


def stream_request(topic, node, **overrides):
    payload = {
        "node_key": node.node_key,
        "topic_id": topic.id,
        "session_id": "server-session",
        "user_input": "current answer",
        "request_id": str(uuid.uuid4()),
        "mode": "socratic",
        "ai_style": "标准",
        "kind": "qa",
    }
    payload.update(overrides)
    return payload


def parse_events(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: {")
    ]


def test_stream_uses_all_complete_server_messages_within_budget(
    client, db_session, auth_user, monkeypatch
):
    topic, node = create_chat_node(db_session, auth_user)
    for index in range(12):
        db_session.add(
            ChatMessage(
                user_id=auth_user.id,
                topic_id=topic.id,
                session_id="server-session",
                node_key=node.node_key,
                role="user" if index % 2 == 0 else "ai",
                content=f"server-{index}",
                mode="socratic",
                message_type="chat",
                metadata_json={"status": "complete"},
            )
        )
    db_session.add_all(
        [
            ChatMessage(
                user_id=auth_user.id,
                topic_id=topic.id,
                session_id="server-session",
                node_key=node.node_key,
                role="ai",
                content="partial",
                mode="socratic",
                message_type="chat",
                metadata_json={"status": "interrupted"},
            ),
            ChatMessage(
                user_id=auth_user.id,
                topic_id=topic.id,
                session_id="other-session",
                node_key=node.node_key,
                role="ai",
                content="other session",
                mode="socratic",
                message_type="chat",
            ),
            ChatMessage(
                user_id=auth_user.id,
                topic_id=topic.id,
                session_id="server-session",
                node_key=node.node_key,
                role="ai",
                content="structured step",
                mode="socratic",
                message_type="agent_step",
            ),
        ]
    )
    db_session.commit()
    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return iter(["reply"])

    monkeypatch.setattr("routers.chat.chat_stream", fake_stream)
    response = client.post("/api/chat/stream", json=stream_request(topic, node))

    assert response.status_code == 200
    assert [message["content"] for message in captured["messages"]] == [
        f"server-{index}" for index in range(12)
    ]
    assert "forged history" not in str(captured["messages"])


def test_stream_persists_quote_target_in_user_message(client, db_session, auth_user, monkeypatch):
    topic, node = create_chat_node(db_session, auth_user)
    source = ChatMessage(
        user_id=auth_user.id,
        topic_id=topic.id,
        session_id="server-session",
        node_key=node.node_key,
        role="ai",
        content="original answer",
        mode="socratic",
        message_type="chat",
        metadata_json={"status": "complete"},
    )
    db_session.add(source)
    db_session.commit()
    monkeypatch.setattr("routers.chat.chat_stream", lambda **_kwargs: iter(["reply"]))

    response = client.post(
        "/api/chat/stream",
        json=stream_request(
            topic,
            node,
            user_input="> original answer\n\nwhy?",
            quote_text="original answer",
            quote_source_id=source.id,
        ),
    )

    assert response.status_code == 200
    user_message = db_session.query(ChatMessage).filter(ChatMessage.role == "user").one()
    assert {
        key: value
        for key, value in user_message.metadata_json.items()
        if key not in {"request_id", "kind", "attachment_derived", "attachment_snapshot"}
    } == {
        "status": "complete",
        "quote": "original answer",
        "quote_source_id": source.id,
    }

    invalid = client.post(
        "/api/chat/stream",
        json=stream_request(
            topic,
            node,
            session_id="other-session",
            quote_text="original answer",
            quote_source_id=source.id,
        ),
    )
    assert invalid.status_code == 400


def test_only_socratic_learning_chat_receives_memories(client, db_session, auth_user, monkeypatch):
    topic, node = create_chat_node(db_session, auth_user)
    other_topic = Topic(user_id=auth_user.id, title="Other")
    db_session.add(other_topic)
    db_session.flush()
    db_session.add_all(
        [
            LearnerMemory(
                user_id=auth_user.id,
                topic_id=topic.id,
                kind="preference",
                content="Use examples",
                source="user",
            ),
            LearnerMemory(
                user_id=auth_user.id,
                topic_id=None,
                kind="background",
                content="New programmer",
                source="user",
            ),
            LearnerMemory(
                user_id=auth_user.id,
                topic_id=other_topic.id,
                kind="goal",
                content="Do not leak",
                source="user",
            ),
        ]
    )
    db_session.commit()
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs)
        return iter(["reply"])

    monkeypatch.setattr("routers.chat.chat_stream", fake_stream)
    before = db_session.query(LearnerMemory).count()
    client.post("/api/chat/stream", json=stream_request(topic, node))
    client.post(
        "/api/chat/stream",
        json=stream_request(
            topic, node, mode="normal", user_input="hello", session_id="normal-session", topic_id=0
        ),
    )

    assert [item["content"] for item in calls[0]["memories"]] == [
        "Use examples",
        "New programmer",
    ]
    assert calls[1]["memories"] == []
    assert db_session.query(LearnerMemory).count() == before


def test_stream_failure_is_persisted_as_incomplete_message(
    client, db_session, auth_user, monkeypatch
):
    topic, node = create_chat_node(db_session, auth_user)

    def failed_stream(**_kwargs):
        def generate():
            yield "partial"
            raise RuntimeError("provider unavailable")

        return generate()

    monkeypatch.setattr("routers.chat.chat_stream", failed_stream)
    response = client.post("/api/chat/stream", json=stream_request(topic, node))

    assert response.status_code == 200
    events = parse_events(response)
    assert next(event["error"] for event in events if "error" in event)["code"] == "AI_STREAM_ERROR"
    messages = db_session.query(ChatMessage).order_by(ChatMessage.id).all()
    assert messages[0].metadata_json["status"] == "complete"
    assert messages[1].content == "partial"
    assert messages[1].metadata_json["status"] == "failed"


def test_success_stream_returns_persisted_message_ids(client, db_session, auth_user, monkeypatch):
    topic, node = create_chat_node(db_session, auth_user)

    monkeypatch.setattr(
        "routers.chat.chat_stream",
        lambda **_kwargs: iter(["reply"]),
    )
    response = client.post("/api/chat/stream", json=stream_request(topic, node))

    assert response.status_code == 200
    events = parse_events(response)
    ids = next(event["msg_ids"] for event in events if "msg_ids" in event)
    messages = db_session.query(ChatMessage).order_by(ChatMessage.id).all()
    assert ids == {"user": messages[0].id, "ai": messages[1].id}
    assert messages[1].metadata_json["status"] == "complete"


def test_history_exposes_structured_message_fields(client, db_session, auth_user):
    topic, node = create_chat_node(db_session, auth_user)
    db_session.add(
        ChatMessage(
            user_id=auth_user.id,
            topic_id=topic.id,
            session_id="server-session",
            node_key=node.node_key,
            role="ai",
            content="Step 2 of 3",
            mode="socratic",
            message_type="agent_step",
            metadata_json={"current": 2, "total": 3},
        )
    )
    db_session.commit()

    response = client.get(f"/api/chat/history/{node.node_key}")

    assert response.status_code == 200
    assert response.json()[0]["message_type"] == "agent_step"
    assert response.json()[0]["metadata"] == {"current": 2, "total": 3}
    all_messages = client.get("/api/chat/messages")
    assert all_messages.status_code == 200
    assert all_messages.json()[0]["metadata"] == {"current": 2, "total": 3}


def test_topic_overview_requires_an_owned_topic(client, db_session, auth_user):
    other = User(
        username="chat-other",
        email="chat-other@example.com",
        hashed_password="hash",
    )
    db_session.add(other)
    db_session.flush()
    topic = Topic(user_id=other.id, title="Private topic")
    db_session.add(topic)
    db_session.commit()

    response = client.post(
        "/api/chat/stream",
        json={
            "request_id": str(uuid.uuid4()),
            "node_key": "Private topic",
            "topic_id": topic.id,
            "session_id": "new-session",
            "user_input": "",
            "mode": "socratic",
            "ai_style": "标准",
            "kind": "topic_overview",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "主题不存在"


def test_qa_rejects_blank_user_input(client, db_session, auth_user):
    topic, node = create_chat_node(db_session, auth_user)
    response = client.post(
        "/api/chat/stream",
        json=stream_request(topic, node, user_input=" "),
    )

    assert response.status_code == 422
