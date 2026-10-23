from datetime import date

import pytest

from core.errors import ApiError
from models import (
    AgentRun,
    AssessmentAttempt,
    MasteryEvent,
    Node,
    StudyPlan,
    StudyPlanItem,
    Topic,
    User,
)
from models.enums import MasterySource
from services.mastery import record_mastery, revert_mastery


def create_graph_with_plan(db_session, user):
    topic = Topic(user_id=user.id, title="Mastery")
    db_session.add(topic)
    db_session.flush()
    nodes = {
        "root": Node(topic_id=topic.id, node_key="root", label="Root", state="mastered"),
        "a": Node(
            topic_id=topic.id, node_key="a", label="A", state="available", parent_keys="root"
        ),
        "b": Node(topic_id=topic.id, node_key="b", label="B", state="mastered", parent_keys="root"),
        "child": Node(
            topic_id=topic.id, node_key="child", label="Child", state="locked", parent_keys="a,b"
        ),
        "mastered-child": Node(
            topic_id=topic.id,
            node_key="mastered-child",
            label="Mastered child",
            state="mastered",
            parent_keys="a",
        ),
        "leaf": Node(
            topic_id=topic.id,
            node_key="leaf",
            label="Leaf",
            state="available",
            parent_keys="mastered-child",
        ),
    }
    db_session.add_all(nodes.values())
    plan = StudyPlan(
        user_id=user.id,
        topic_id=topic.id,
        goal="Master the graph",
        domain="education",
        outcome_type="concept",
        daily_minutes=30,
        timezone="UTC",
        start_date=date(2026, 9, 7),
        estimated_end_date=date(2026, 9, 12),
        status="active",
    )
    db_session.add(plan)
    db_session.flush()
    item = StudyPlanItem(
        plan_id=plan.id,
        node_id=nodes["a"].id,
        scheduled_date=date(2026, 9, 8),
        day_order=1,
        estimated_minutes=30,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()
    return topic, nodes, item


def test_self_reported_mastery_completes_plan_and_unlocks_all_parent_child(db_session, auth_user):
    _topic, nodes, item = create_graph_with_plan(db_session, auth_user)

    first = record_mastery(
        db_session,
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        source=MasterySource.SELF_REPORTED,
        request_id="master-a",
    )
    second = record_mastery(
        db_session,
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        source=MasterySource.SELF_REPORTED,
        request_id="master-a",
    )

    db_session.refresh(nodes["a"])
    db_session.refresh(nodes["child"])
    db_session.refresh(item)
    assert first.event_id == second.event_id
    assert db_session.query(MasteryEvent).filter_by(request_id="master-a").count() == 1
    assert nodes["a"].state == "mastered"
    assert nodes["a"].mastery_source == "self_reported"
    assert nodes["a"].mastery_confidence is None
    assert nodes["child"].state == "available"
    assert item.status == "completed"
    assert item.completed_at is not None


def test_assessment_mastery_requires_matching_evidence(db_session, auth_user):
    topic, nodes, _item = create_graph_with_plan(db_session, auth_user)
    run = AgentRun(
        id="00000000-0000-0000-0000-000000000099",
        user_id=auth_user.id,
        topic_id=topic.id,
        run_type="assessment",
        status="completed",
        state_json={},
    )
    db_session.add(run)
    db_session.flush()
    attempt = AssessmentAttempt(
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        run_id=run.id,
        status="completed",
        questions_json=[],
        answers_json=[],
        rubrics_json=[],
        total_score=10,
        evaluation_confidence=0.82,
        critical_misconception=False,
    )
    db_session.add(attempt)
    db_session.commit()

    result = record_mastery(
        db_session,
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        source=MasterySource.ASSESSMENT,
        request_id="assessment-master",
        assessment_id=attempt.id,
    )

    event = db_session.get(MasteryEvent, result.event_id)
    assert event.assessment_id == attempt.id
    assert event.total_score == 10
    assert event.confidence == pytest.approx(0.82)

    with pytest.raises(ApiError) as error:
        record_mastery(
            db_session,
            user_id=auth_user.id,
            node_id=nodes["leaf"].id,
            source=MasterySource.ASSESSMENT,
            request_id="missing-evidence",
        )
    assert error.value.code == "ASSESSMENT_EVIDENCE_REQUIRED"


def test_revert_recomputes_unmastered_descendants_and_keeps_mastered_evidence(
    db_session, auth_user
):
    _topic, nodes, item = create_graph_with_plan(db_session, auth_user)
    record_mastery(
        db_session,
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        source=MasterySource.SELF_REPORTED,
        request_id="master-before-revert",
    )

    first = revert_mastery(
        db_session,
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        request_id="revert-a",
    )
    second = revert_mastery(
        db_session,
        user_id=auth_user.id,
        node_id=nodes["a"].id,
        request_id="revert-a",
    )

    for node in nodes.values():
        db_session.refresh(node)
    db_session.refresh(item)
    assert first.event_id == second.event_id
    assert nodes["a"].state == "available"
    assert nodes["child"].state == "locked"
    assert nodes["mastered-child"].state == "mastered"
    assert nodes["leaf"].state == "available"
    assert item.status == "pending"
    assert item.completed_at is None


def test_mastery_hides_nodes_owned_by_another_user(db_session, auth_user):
    other = User(username="other", email="other@example.com", hashed_password="hash")
    db_session.add(other)
    db_session.commit()
    _topic, nodes, _item = create_graph_with_plan(db_session, other)

    with pytest.raises(ApiError) as error:
        record_mastery(
            db_session,
            user_id=auth_user.id,
            node_id=nodes["a"].id,
            source=MasterySource.SELF_REPORTED,
            request_id="cross-user",
        )
    assert error.value.status_code == 404
    assert error.value.code == "NODE_NOT_FOUND"
