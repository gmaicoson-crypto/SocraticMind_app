import json

from models.node import Node
from models.progress import ChatMessage
from models.topic import Topic


def test_topic_generation_requires_onboarding(client, db_session):
    response = client.post("/api/topics/generate", json={"title": "Testing"})

    assert response.status_code == 409
    assert response.json()["code"] == "ONBOARDING_REQUIRED"
    assert db_session.query(Node).count() == 0


def test_legacy_master_endpoint_unlocks_child(client, db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Graph")
    db_session.add(topic)
    db_session.flush()
    root = Node(
        topic_id=topic.id,
        node_key="root",
        label="Root",
        state="available",
        parent_keys="",
    )
    child = Node(
        topic_id=topic.id,
        node_key="child",
        label="Child",
        state="locked",
        parent_keys="root",
    )
    db_session.add_all([root, child])
    db_session.commit()

    response = client.put(f"/api/nodes/{root.id}/master")

    assert response.status_code == 200
    db_session.refresh(child)
    assert response.json()["state"] == "mastered"
    assert child.state == "available"


def test_legacy_master_endpoint_keeps_locked_error_shape(client, db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Locked graph")
    db_session.add(topic)
    db_session.flush()
    locked = Node(
        topic_id=topic.id,
        node_key="locked",
        label="Locked",
        state="locked",
        parent_keys="missing",
    )
    db_session.add(locked)
    db_session.commit()

    response = client.put(f"/api/nodes/{locked.id}/master")

    assert response.status_code == 400
    assert response.json() == {"detail": "节点尚未解锁"}


def test_chat_stream_treats_mastered_marker_as_plain_text(
    client, db_session, auth_user, monkeypatch
):
    topic = Topic(user_id=auth_user.id, title="Streaming")
    db_session.add(topic)
    db_session.flush()
    node = Node(
        topic_id=topic.id,
        node_key="stream-node",
        label="Stream Node",
        state="available",
        parent_keys="",
    )
    db_session.add(node)
    db_session.commit()
    monkeypatch.setattr("routers.chat.chat_stream", lambda **_: iter(["Good work ", "[MASTERED]"]))

    response = client.post(
        "/api/chat/stream",
        json={
            "node_key": node.node_key,
            "topic_id": topic.id,
            "session_id": "legacy-session",
            "user_input": "answer",
            "request_id": "plain-marker-request",
        },
    )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: {")
    ]
    assert "".join(event.get("text", "") for event in events) == "Good work [MASTERED]"
    assert not any("signal" in event for event in events)
    assert any("msg_ids" in event for event in events)
    messages = db_session.query(ChatMessage).order_by(ChatMessage.id).all()
    assert [message.role for message in messages] == ["user", "ai"]
    assert messages[-1].content == "Good work [MASTERED]"
    assert messages[-1].metadata_json["status"] == "complete"
    db_session.refresh(node)
    assert node.state == "available"
