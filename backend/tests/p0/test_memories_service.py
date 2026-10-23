from models import LearnerMemory, Node, Topic
from models.enums import MemoryKind
from services.memories import (
    create_memory,
    delete_memory,
    select_relevant_memories,
    update_memory,
    upsert_assessment_memories,
)


def test_memory_crud_and_deleted_memory_leaves_context(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Memory topic")
    db_session.add(topic)
    db_session.commit()
    memory = create_memory(
        db_session,
        user_id=auth_user.id,
        kind=MemoryKind.GOAL,
        content="Learn the basics",
        topic_id=topic.id,
    )
    assert memory.source == "user"

    memory = update_memory(
        db_session,
        user_id=auth_user.id,
        memory_id=memory.id,
        updates={"content": "Learn the advanced material", "topic_id": None},
    )
    assert memory.topic_id is None
    assert memory.content == "Learn the advanced material"
    assert [item.id for item in select_relevant_memories(db_session, user_id=auth_user.id)] == [
        memory.id
    ]

    delete_memory(db_session, user_id=auth_user.id, memory_id=memory.id)
    assert select_relevant_memories(db_session, user_id=auth_user.id) == []


def test_context_prefers_topic_scope_and_respects_count_and_character_budget(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Scoped")
    db_session.add(topic)
    db_session.flush()
    for index in range(12):
        db_session.add(
            LearnerMemory(
                user_id=auth_user.id,
                topic_id=topic.id,
                kind="weakness",
                content=f"topic-{index}-" + "x" * 190,
                source="assessment",
            )
        )
    for index in range(12):
        db_session.add(
            LearnerMemory(
                user_id=auth_user.id,
                topic_id=None,
                kind="preference",
                content=f"global-{index}-" + "y" * 190,
                source="user",
            )
        )
    db_session.commit()

    selected = select_relevant_memories(db_session, user_id=auth_user.id, topic_id=topic.id)

    assert len(selected) <= 20
    assert sum(len(item.content) for item in selected) <= 3000
    assert all(item.topic_id == topic.id for item in selected[:12])


def test_assessment_memories_are_upserted(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="Assessment memory")
    db_session.add(topic)
    db_session.flush()
    node = Node(topic_id=topic.id, node_key="root", label="Root", state="available")
    db_session.add(node)
    db_session.commit()

    upsert_assessment_memories(
        db_session,
        user_id=auth_user.id,
        node=node,
        weaknesses=["Needs clearer boundaries"],
        passed=False,
        confidence=0.8,
    )
    db_session.commit()
    upsert_assessment_memories(
        db_session,
        user_id=auth_user.id,
        node=node,
        weaknesses=["Needs clearer boundaries"],
        passed=False,
        confidence=0.9,
    )
    db_session.commit()

    memories = db_session.query(LearnerMemory).all()
    assert len(memories) == 1
    assert memories[0].kind == "weakness"
    assert memories[0].confidence == 0.9
