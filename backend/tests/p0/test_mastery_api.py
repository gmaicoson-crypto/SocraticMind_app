from sqlalchemy import event

from models import User
from routers.agent import get_agent_generator
from tests.p0.test_assessment_service import AssessmentGenerator, create_assessable_node


def test_assessment_api_and_answer_protocol(app, client, db_session, auth_user):
    node, _item = create_assessable_node(db_session, auth_user)
    app.dependency_overrides[get_agent_generator] = lambda: AssessmentGenerator()

    started = client.post(
        "/api/agent/assessments",
        json={"node_id": node.id, "request_id": "api-assessment"},
    )
    assert started.status_code == 201
    run = started.json()
    assert run["step"]["current"] == 1
    for index in range(3):
        response = client.post(
            f"/api/agent/runs/{run['run_id']}/answers",
            json={
                "step_id": run["step"]["step_id"],
                "version": run["version"],
                "answer": f"answer {index}",
            },
        )
        assert response.status_code == 200
        run = response.json()
    assert run["result"]["passed"] is True
    assert run["result"]["node_id"] == node.id

    selects = []

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", count_selects)
    try:
        nodes = client.get(f"/api/nodes/topic/{node.topic_id}")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_selects)
    assert nodes.status_code == 200
    assert len(selects) <= 3
    node_payload = next(item for item in nodes.json() if item["id"] == node.id)
    assert node_payload["mastery_source"] == "assessment"
    assert node_payload["assessment_result"]["passed"] is True


def test_self_report_and_revert_are_idempotent(app, client, db_session, auth_user):
    node, _item = create_assessable_node(db_session, auth_user)

    first = client.post(f"/api/nodes/{node.id}/mastery", json={"request_id": "self-master"})
    second = client.post(f"/api/nodes/{node.id}/mastery", json={"request_id": "self-master"})
    assert first.status_code == second.status_code == 200
    assert first.json()["event_id"] == second.json()["event_id"]

    reverted = client.post(
        f"/api/nodes/{node.id}/mastery/revert", json={"request_id": "undo-master"}
    )
    repeated = client.post(
        f"/api/nodes/{node.id}/mastery/revert", json={"request_id": "undo-master"}
    )
    assert reverted.status_code == repeated.status_code == 200
    assert reverted.json()["state"] == "available"


def test_mastery_api_hides_other_users_node(client, db_session):
    owner = User(username="master-owner", email="master-owner@example.com", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    node, _item = create_assessable_node(db_session, owner)

    response = client.post(f"/api/nodes/{node.id}/mastery", json={"request_id": "cross-master"})
    assert response.status_code == 404
    assert response.json()["code"] == "NODE_NOT_FOUND"
