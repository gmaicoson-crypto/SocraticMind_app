from datetime import datetime, timedelta, timezone

from models import Node, StudyPlan, StudyPlanItem, Topic, User
from services.planning import today_in_timezone


def create_plan(db_session, user, *, title="Plan"):
    today, _ = today_in_timezone("UTC")
    topic = Topic(user_id=user.id, title=title, emoji="📘")
    db_session.add(topic)
    db_session.flush()
    root = Node(
        topic_id=topic.id,
        node_key="root",
        label="Root",
        state="mastered",
        estimated_minutes=20,
    )
    child = Node(
        topic_id=topic.id,
        node_key="child",
        label="Child",
        state="available",
        parent_keys="root",
        estimated_minutes=40,
    )
    leaf = Node(
        topic_id=topic.id,
        node_key="leaf",
        label="Leaf",
        state="locked",
        parent_keys="child",
        estimated_minutes=20,
    )
    db_session.add_all([root, child, leaf])
    db_session.flush()
    plan = StudyPlan(
        user_id=user.id,
        topic_id=topic.id,
        goal="Finish",
        domain="education",
        outcome_type="concept",
        daily_minutes=30,
        timezone="UTC",
        start_date=today - timedelta(days=2),
        target_date=today,
        estimated_end_date=today + timedelta(days=1),
        status="active",
    )
    db_session.add(plan)
    db_session.flush()
    completed_at = datetime.now(timezone.utc)
    items = [
        StudyPlanItem(
            plan_id=plan.id,
            node_id=root.id,
            scheduled_date=today - timedelta(days=2),
            day_order=1,
            estimated_minutes=20,
            status="completed",
            completed_at=completed_at,
        ),
        StudyPlanItem(
            plan_id=plan.id,
            node_id=child.id,
            scheduled_date=today - timedelta(days=1),
            day_order=1,
            estimated_minutes=10,
            status="pending",
        ),
        StudyPlanItem(
            plan_id=plan.id,
            node_id=child.id,
            scheduled_date=today,
            day_order=1,
            estimated_minutes=30,
            status="pending",
        ),
        StudyPlanItem(
            plan_id=plan.id,
            node_id=leaf.id,
            scheduled_date=today + timedelta(days=1),
            day_order=1,
            estimated_minutes=20,
            status="pending",
        ),
    ]
    db_session.add_all(items)
    db_session.commit()
    return topic, plan, items


def test_today_plan_groups_items_and_reports_timezone(client, db_session, auth_user):
    topic, plan, _items = create_plan(db_session, auth_user)

    response = client.get("/api/plans/today", params={"timezone": "Invalid/Zone"})

    assert response.status_code == 200
    body = response.json()
    assert body["effective_timezone"] == "UTC"
    assert body["replan_suggested"] is True
    assert [item["node_label"] for item in body["today"]] == ["Child"]
    assert [item["node_label"] for item in body["overdue"]] == ["Child"]
    assert [item["node_label"] for item in body["upcoming"]] == ["Leaf"]
    assert body["today"][0]["topic_id"] == topic.id
    assert body["today"][0]["plan_id"] == plan.id


def test_topic_plan_and_replan_are_idempotent(client, db_session, auth_user):
    topic, plan, items = create_plan(db_session, auth_user)
    completed = items[0]

    detail = client.get(f"/api/topics/{topic.id}/plan")
    assert detail.status_code == 200
    assert detail.json()["version"] == 1
    assert detail.json()["will_miss_target"] is True

    first = client.post(
        f"/api/plans/{plan.id}/replan",
        json={"request_id": "replan-1", "timezone": "UTC"},
    )
    second = client.post(
        f"/api/plans/{plan.id}/replan",
        json={"request_id": "replan-1", "timezone": "UTC"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["version"] == 2
    assert second.json()["version"] == 2
    db_session.refresh(completed)
    assert completed.status == "completed"
    assert completed.scheduled_date == items[0].scheduled_date


def test_missing_and_cross_user_plans_do_not_leak(client, app, db_session, auth_user):
    empty_topic = Topic(user_id=auth_user.id, title="No plan")
    other = User(username="plan-other", email="plan-other@example.com", hashed_password="hash")
    db_session.add_all([empty_topic, other])
    db_session.commit()
    _other_topic, other_plan, _items = create_plan(db_session, other, title="Other")

    missing = client.get(f"/api/topics/{empty_topic.id}/plan")
    cross_user = client.post(
        f"/api/plans/{other_plan.id}/replan", json={"request_id": "cross-user"}
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "PLAN_NOT_FOUND"
    assert cross_user.status_code == 404
    assert cross_user.json()["code"] == "PLAN_NOT_FOUND"
