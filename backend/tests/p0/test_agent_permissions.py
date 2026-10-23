from models import Node, Topic, User
from core.deps import get_current_user
from routers.agent import get_agent_generator
from tests.p0.test_agent_api import fake_generator, onboarding_payload


def test_run_ids_are_scoped_to_current_user(app, client, db_session, auth_user):
    app.dependency_overrides[get_agent_generator] = lambda: fake_generator
    run = client.post("/api/agent/onboarding", json=onboarding_payload()).json()
    other = User(username="other-api", email="other-api@example.com", hashed_password="hash")
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other

    response = client.get(f"/api/agent/runs/{run['run_id']}")
    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"


def test_existing_topic_plan_does_not_change_nodes(app, client, db_session, auth_user):
    app.dependency_overrides[get_agent_generator] = lambda: fake_generator
    topic = Topic(user_id=auth_user.id, title="Existing")
    db_session.add(topic)
    db_session.flush()
    nodes = [
        Node(
            topic_id=topic.id, node_key="root", label="Root", state="mastered", estimated_minutes=20
        ),
        Node(
            topic_id=topic.id,
            node_key="a",
            label="A",
            state="available",
            parent_keys="root",
            estimated_minutes=20,
        ),
        Node(
            topic_id=topic.id,
            node_key="b",
            label="B",
            state="available",
            parent_keys="root",
            estimated_minutes=20,
        ),
        Node(
            topic_id=topic.id,
            node_key="c",
            label="C",
            state="locked",
            parent_keys="a,b",
            estimated_minutes=20,
        ),
        Node(
            topic_id=topic.id,
            node_key="d",
            label="D",
            state="locked",
            parent_keys="c",
            estimated_minutes=20,
        ),
        Node(
            topic_id=topic.id,
            node_key="e",
            label="E",
            state="locked",
            parent_keys="d",
            estimated_minutes=20,
        ),
    ]
    db_session.add_all(nodes)
    db_session.commit()
    before = [(node.id, node.node_key, node.state, node.parent_keys) for node in nodes]

    payload = onboarding_payload(False)
    payload.pop("topic")
    started = client.post(f"/api/agent/topics/{topic.id}/plan-runs", json=payload)
    assert started.status_code == 201
    assert len(started.json()["preview"]["plan_items"]) > 0
    assert all(item["node_key"] != "root" for item in started.json()["preview"]["plan_items"])
    confirmed = client.post(
        f"/api/agent/runs/{started.json()['run_id']}/confirm",
        json={"request_id": "existing-confirm"},
    )
    assert confirmed.status_code == 200

    db_session.expire_all()
    after_nodes = db_session.query(Node).filter_by(topic_id=topic.id).order_by(Node.id).all()
    after = [(node.id, node.node_key, node.state, node.parent_keys) for node in after_nodes]
    assert after == before


def test_existing_topic_confirmation_rejects_a_stale_node_snapshot(
    app, client, db_session, auth_user
):
    app.dependency_overrides[get_agent_generator] = lambda: fake_generator
    topic = Topic(user_id=auth_user.id, title="Changing")
    db_session.add(topic)
    db_session.flush()
    nodes = [
        Node(topic_id=topic.id, node_key="root", label="Root", state="available"),
        Node(topic_id=topic.id, node_key="a", label="A", state="locked", parent_keys="root"),
        Node(topic_id=topic.id, node_key="b", label="B", state="locked", parent_keys="root"),
        Node(topic_id=topic.id, node_key="c", label="C", state="locked", parent_keys="a,b"),
        Node(topic_id=topic.id, node_key="d", label="D", state="locked", parent_keys="c"),
        Node(topic_id=topic.id, node_key="e", label="E", state="locked", parent_keys="d"),
    ]
    db_session.add_all(nodes)
    db_session.commit()
    payload = onboarding_payload(False)
    payload.pop("topic")
    run = client.post(f"/api/agent/topics/{topic.id}/plan-runs", json=payload).json()

    nodes[1].label = "Changed after preview"
    db_session.commit()
    response = client.post(
        f"/api/agent/runs/{run['run_id']}/confirm",
        json={"request_id": "stale-confirm"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AGENT_STATE_CONFLICT"
    assert db_session.query(Node).filter_by(topic_id=topic.id).count() == 6
