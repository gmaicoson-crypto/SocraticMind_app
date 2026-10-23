from datetime import date

from models import (
    AgentRun,
    AssessmentAttempt,
    LearnerMemory,
    MasteryEvent,
    Node,
    StudyPlan,
    StudyPlanItem,
    Topic,
)


def test_p0_relationships_are_navigable(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Relationships")
    db_session.add(topic)
    db_session.flush()
    node = Node(
        topic_id=topic.id,
        node_key="root",
        label="Root",
        state="available",
        estimated_minutes=30,
    )
    run = AgentRun(
        id="00000000-0000-0000-0000-000000000001",
        user_id=auth_user.id,
        topic_id=topic.id,
        run_type="assessment",
        status="assessing",
        state_json={},
    )
    memory = LearnerMemory(
        user_id=auth_user.id,
        topic_id=topic.id,
        kind="goal",
        content="Understand the topic",
        source="user",
    )
    plan = StudyPlan(
        user_id=auth_user.id,
        topic_id=topic.id,
        goal="Understand the topic",
        domain="education",
        outcome_type="concept",
        daily_minutes=30,
        timezone="UTC",
        start_date=date(2026, 9, 7),
        estimated_end_date=date(2026, 9, 7),
        status="active",
    )
    db_session.add_all([node, run, memory, plan])
    db_session.flush()
    item = StudyPlanItem(
        plan_id=plan.id,
        node_id=node.id,
        scheduled_date=date(2026, 9, 7),
        day_order=1,
        estimated_minutes=30,
        status="pending",
    )
    attempt = AssessmentAttempt(
        user_id=auth_user.id,
        node_id=node.id,
        run_id=run.id,
        status="active",
        questions_json=[],
        answers_json=[],
        rubrics_json=[],
    )
    db_session.add_all([item, attempt])
    db_session.flush()
    event = MasteryEvent(
        user_id=auth_user.id,
        node_id=node.id,
        assessment_id=attempt.id,
        source="assessment",
        from_state="available",
        to_state="mastered",
        request_id="master-1",
    )
    db_session.add(event)
    db_session.commit()

    assert auth_user.agent_runs == [run]
    assert auth_user.memories == [memory]
    assert topic.study_plan is plan
    assert plan.items == [item]
    assert node.assessment_attempts == [attempt]
    assert attempt.mastery_events == [event]


def test_deleting_user_cascades_p0_records(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Cascade")
    node = Node(
        topic=topic,
        node_key="cascade-root",
        label="Root",
        state="available",
        estimated_minutes=20,
    )
    run = AgentRun(
        id="00000000-0000-0000-0000-000000000002",
        user=auth_user,
        topic=topic,
        run_type="onboarding",
        status="collecting",
        state_json={},
    )
    memory = LearnerMemory(
        user=auth_user,
        topic=topic,
        kind="preference",
        content="Short sessions",
        source="user",
    )
    plan = StudyPlan(
        user=auth_user,
        topic=topic,
        goal="Test cascade",
        domain="testing",
        outcome_type="concept",
        daily_minutes=20,
        timezone="UTC",
        start_date=date(2026, 9, 7),
        estimated_end_date=date(2026, 9, 7),
        status="active",
    )
    db_session.add_all([topic, node, run, memory, plan])
    db_session.flush()
    item = StudyPlanItem(
        plan=plan,
        node=node,
        scheduled_date=date(2026, 9, 7),
        day_order=1,
        estimated_minutes=20,
        status="pending",
    )
    attempt = AssessmentAttempt(
        user=auth_user,
        node=node,
        run=run,
        status="active",
        questions_json=[],
        answers_json=[],
        rubrics_json=[],
    )
    event = MasteryEvent(
        user=auth_user,
        node=node,
        assessment=attempt,
        source="assessment",
        from_state="available",
        to_state="mastered",
        request_id="cascade-master",
    )
    db_session.add_all([item, attempt, event])
    db_session.commit()

    db_session.delete(auth_user)
    db_session.commit()

    assert db_session.query(AgentRun).count() == 0
    assert db_session.query(LearnerMemory).count() == 0
    assert db_session.query(Topic).count() == 0
    assert db_session.query(Node).count() == 0
    assert db_session.query(StudyPlan).count() == 0
    assert db_session.query(StudyPlanItem).count() == 0
    assert db_session.query(AssessmentAttempt).count() == 0
    assert db_session.query(MasteryEvent).count() == 0
