from models import LearnerMemory, Topic, User


def test_memory_api_crud_and_filters(client, db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="API memory")
    db_session.add(topic)
    db_session.commit()

    created = client.post(
        "/api/agent/memories",
        json={"kind": "goal", "content": "Learn deeply", "topic_id": topic.id},
    )
    assert created.status_code == 201
    memory = created.json()
    assert memory["source"] == "user"

    listed = client.get("/api/agent/memories", params={"topic_id": topic.id, "kind": "goal"})
    assert [item["id"] for item in listed.json()] == [memory["id"]]

    updated = client.patch(
        f"/api/agent/memories/{memory['id']}",
        json={"kind": "preference", "content": "Use examples"},
    )
    assert updated.status_code == 200
    assert updated.json()["kind"] == "preference"

    deleted = client.delete(f"/api/agent/memories/{memory['id']}")
    assert deleted.status_code == 204
    assert db_session.query(LearnerMemory).count() == 0


def test_memory_api_rejects_long_content_and_foreign_scope(client, db_session):
    other = User(username="memory-other", email="memory-other@example.com", hashed_password="hash")
    db_session.add(other)
    db_session.flush()
    topic = Topic(user_id=other.id, title="Private")
    private_memory = LearnerMemory(
        user_id=other.id,
        topic=topic,
        kind="goal",
        content="Private goal",
        source="user",
    )
    db_session.add(private_memory)
    db_session.commit()

    too_long = client.post("/api/agent/memories", json={"kind": "goal", "content": "x" * 301})
    foreign_topic = client.post(
        "/api/agent/memories",
        json={"kind": "goal", "content": "No access", "topic_id": topic.id},
    )
    foreign_memory = client.patch(
        f"/api/agent/memories/{private_memory.id}", json={"content": "Changed"}
    )

    assert too_long.status_code == 422
    assert foreign_topic.status_code == 404
    assert foreign_topic.json()["code"] == "TOPIC_NOT_FOUND"
    assert foreign_memory.status_code == 404
    assert foreign_memory.json()["code"] == "MEMORY_NOT_FOUND"
