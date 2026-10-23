from datetime import datetime, timezone

from models import AgentRun, ArchivedChatActivity, ArchivedMastery, ChatMessage, Node, Topic, User


def add_message(db, user_id, *, topic_id, session_id, role="user", mode="socratic"):
    message = ChatMessage(
        user_id=user_id,
        topic_id=topic_id,
        session_id=session_id,
        node_key="node",
        role=role,
        content="private conversation text",
        mode=mode,
    )
    db.add(message)
    db.flush()
    return message.id


def test_deleted_session_retains_only_learning_activity(client, db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Study")
    db_session.add(topic)
    db_session.flush()
    add_message(db_session, auth_user.id, topic_id=topic.id, session_id="gone")
    add_message(db_session, auth_user.id, topic_id=topic.id, session_id="gone", role="ai")
    add_message(db_session, auth_user.id, topic_id=topic.id, session_id="gone", mode="normal")
    add_message(db_session, auth_user.id, topic_id=topic.id, session_id="kept")
    db_session.add(
        AgentRun(
            user_id=auth_user.id,
            topic_id=topic.id,
            session_id="gone",
            run_type="assessment",
            state_json={"answer": "private conversation text"},
        )
    )
    db_session.commit()

    before = client.get("/api/progress/stats").json()
    deleted = client.request("DELETE", "/api/chat/session", json={"session_id": "gone"})
    after = client.get("/api/progress/stats").json()

    assert deleted.json()["deleted"] == 3
    assert db_session.query(ChatMessage).filter_by(session_id="gone").count() == 0
    assert db_session.query(AgentRun).filter_by(session_id="gone").count() == 0
    assert db_session.query(ArchivedChatActivity).count() == 1
    assert after["chat_count"] == before["chat_count"] == 2
    assert after["heatmap"] == before["heatmap"]
    assert after["weekly"]["chat_count"] == before["weekly"]["chat_count"]
    assert after["weekly"]["peak_hour"] == before["weekly"]["peak_hour"]

    repeated = client.request("DELETE", "/api/chat/session", json={"session_id": "gone"})
    assert repeated.json()["deleted"] == 0
    assert client.get("/api/progress/stats").json()["chat_count"] == 2


def test_deleted_topic_retains_mastery_and_chat_stats(client, db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Calculus")
    db_session.add(topic)
    db_session.flush()
    db_session.add(
        Node(
            topic_id=topic.id,
            node_key="limits",
            label="Limits",
            state="mastered",
            mastered_at=datetime.now(timezone.utc),
        )
    )
    add_message(db_session, auth_user.id, topic_id=topic.id, session_id="topic-session")
    add_message(db_session, auth_user.id, topic_id=None, session_id="topic-session")
    db_session.add(
        AgentRun(
            user_id=auth_user.id,
            topic_id=topic.id,
            session_id="topic-session",
            run_type="onboarding",
            state_json={"answer": "private conversation text"},
        )
    )
    db_session.commit()

    before = client.get("/api/progress/stats").json()
    response = client.delete(f"/api/topics/{topic.id}")
    after = client.get("/api/progress/stats").json()

    assert response.status_code == 200
    assert db_session.query(Topic).filter_by(id=topic.id).count() == 0
    assert db_session.query(Node).filter_by(topic_id=topic.id).count() == 0
    assert db_session.query(ChatMessage).filter_by(topic_id=topic.id).count() == 0
    assert db_session.query(ChatMessage).filter_by(session_id="topic-session").count() == 0
    assert db_session.query(AgentRun).filter_by(topic_id=topic.id).count() == 0
    assert db_session.query(ArchivedMastery).count() == 1
    assert after["chat_count"] == before["chat_count"] == 2
    assert after["heatmap"] == before["heatmap"]
    assert after["mastered_count"] == before["mastered_count"] == 1
    assert after["weekly"]["mastered_count"] == before["weekly"]["mastered_count"]
    assert after["timeline"] == before["timeline"]


def test_message_ids_only_archive_owned_socratic_user_messages(client, db_session, auth_user):
    other = User(username="other", email="other@example.com", hashed_password="hash")
    db_session.add(other)
    db_session.flush()
    owned_id = add_message(db_session, auth_user.id, topic_id=None, session_id="owned")
    ai_id = add_message(db_session, auth_user.id, topic_id=None, session_id="owned", role="ai")
    other_id = add_message(db_session, other.id, topic_id=None, session_id="other")
    db_session.commit()

    response = client.request(
        "DELETE", "/api/chat/messages", json={"ids": [owned_id, ai_id, other_id]}
    )

    assert response.json()["deleted"] == 2
    assert db_session.query(ChatMessage).filter_by(id=other_id).count() == 1
    assert db_session.query(ArchivedChatActivity).count() == 1
    assert client.get("/api/progress/stats").json()["chat_count"] == 1
