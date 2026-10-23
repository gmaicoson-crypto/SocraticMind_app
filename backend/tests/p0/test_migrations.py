from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from core.migrations import assert_database_at_head
from core.avatars import USER_AVATAR_PRESETS


BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_empty_database_upgrades_to_head(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'empty.sqlite'}"

    command.upgrade(alembic_config(database_url), "head")

    inspector = inspect(create_engine(database_url))
    assert {
        "users",
        "topics",
        "nodes",
        "chat_messages",
        "agent_runs",
        "learner_memories",
        "study_plans",
        "study_plan_items",
        "assessment_attempts",
        "mastery_events",
        "user_llm_profiles",
        "archived_chat_activity",
        "archived_mastery",
        "chat_sessions",
        "chat_session_titles",
        "chat_turns",
        "chat_cancellations",
        "web_search_quotas",
    }.issubset(set(inspector.get_table_names()))
    assert {"estimated_minutes", "mastery_source", "mastery_confidence"}.issubset(
        {column["name"] for column in inspector.get_columns("nodes")}
    )
    assert {"message_type", "metadata_json"}.issubset(
        {column["name"] for column in inspector.get_columns("chat_messages")}
    )
    assert "ix_chat_user_session_type_id" in {
        index["name"] for index in inspector.get_indexes("chat_messages")
    }
    assert "config_id" not in {
        column["name"] for column in inspector.get_columns("user_llm_profiles")
    }
    assert {"summary_json", "summary_source_version", "generation_lease_token"}.issubset(
        {column["name"] for column in inspector.get_columns("chat_sessions")}
    )
    assert "uq_chat_turns_user_request" in {
        index["name"] for index in inspector.get_indexes("chat_turns")
    }


def test_web_quota_migration_has_shared_atomic_counter_key(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'quota.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert set(inspector.get_pk_constraint("web_search_quotas")["constrained_columns"]) == {
        "scope",
        "day",
    }
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO web_search_quotas (scope, day) VALUES ('tavily', '2026-09-30')")
        )
        assert connection.scalar(text("SELECT used_queries FROM web_search_quotas")) == 0
    command.downgrade(config, "0010_chat_context_management")
    assert "web_search_quotas" not in inspect(engine).get_table_names()
    assert "chat_messages" in inspect(engine).get_table_names()


def test_legacy_data_is_preserved_and_backfilled(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0001_current_schema_baseline")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, email, hashed_password, is_active) "
                "VALUES (1, 'legacy', 'legacy@example.com', 'hash', 1)"
            )
        )
        connection.execute(text("INSERT INTO topics (id, user_id, title) VALUES (1, 1, 'Legacy')"))
        connection.execute(
            text(
                "INSERT INTO nodes "
                "(id, topic_id, node_key, label, state, parent_keys) "
                "VALUES (1, 1, 'root', 'Root', 'mastered', '')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chat_messages "
                "(id, user_id, topic_id, session_id, node_key, role, content, mode) "
                "VALUES (1, 1, 1, 'session', 'root', 'user', 'hello', 'socratic')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 1
        assert connection.scalar(text("SELECT count(*) FROM topics")) == 1
        assert connection.scalar(text("SELECT count(*) FROM nodes")) == 1
        assert connection.scalar(text("SELECT count(*) FROM chat_messages")) == 1
        assert connection.scalar(text("SELECT mastery_source FROM nodes WHERE id = 1")) == "legacy"
        assert (
            connection.scalar(text("SELECT message_type FROM chat_messages WHERE id = 1")) == "chat"
        )
        profile = connection.execute(
            text(
                "SELECT avatar_grad, bio, daily_goal, ai_style, ai_avatar_url FROM users WHERE id = 1"
            )
        ).one()
        assert all(value is not None for value in profile)
        assert (
            connection.scalar(text("SELECT avatar_url FROM users WHERE id = 1"))
            in USER_AVATAR_PRESETS
        )


def test_legacy_ai_avatar_paths_move_to_grouped_directories(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'ai-avatars.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0008_random_user_avatars")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, avatar_url, ai_avatar_url) "
                "VALUES (1, 'study', 'study@example.test', 'hash', '/avatars/study/boy-read.webp', "
                "'/avatars/AI/AI-female-2.webp'), "
                "(2, 'normal', 'normal@example.test', 'hash', '/avatars/study/boy-read.webp', "
                "'/avatars/AI/AI_normal_3.webp')"
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        urls = (
            connection.execute(text("SELECT ai_avatar_url FROM users ORDER BY id")).scalars().all()
        )
        assert urls == [
            "/avatars/AI/study/AI-female-2.webp",
            "/avatars/AI/normal/AI_normal_3.webp",
        ]


def test_avatar_backfill_preserves_uploaded_images(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'avatars.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0007_avatar_presets")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, avatar_url) VALUES "
                "(1, 'color', 'color@example.test', 'hash', NULL), "
                "(2, 'upload', 'upload@example.test', 'hash', '/static/avatars/upload.webp')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        avatars = {
            row.id: row.avatar_url
            for row in connection.execute(text("SELECT id, avatar_url FROM users"))
        }
        assert avatars[1] in USER_AVATAR_PRESETS
        assert avatars[2] == "/static/avatars/upload.webp"
        assert (
            next(
                column
                for column in inspect(engine).get_columns("users")
                if column["name"] == "avatar_url"
            )["nullable"]
            is False
        )


def test_existing_user_model_survives_config_id_removal(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'user-model.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0004_user_llm_profiles")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (1, 'model-user', 'model@example.com', 'hash', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO user_llm_profiles "
                "(id, user_id, config_id, name, api_key_encrypted, base_url, model) "
                "VALUES ('profile-1', 1, 'legacy-id', 'My model', 'ciphertext', "
                "'https://example.test/v1', 'official-model')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, name, api_key_encrypted, base_url, model FROM user_llm_profiles")
        ).one() == (
            "profile-1",
            "My model",
            "ciphertext",
            "https://example.test/v1",
            "official-model",
        )


def test_p0_downgrade_keeps_legacy_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'downgrade.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "0001_current_schema_baseline")

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())
    assert {"users", "topics", "nodes", "chat_messages"}.issubset(tables)
    assert "agent_runs" not in tables
    assert "study_plans" not in tables
    assert "mastery_events" not in tables
    assert "chat_sessions" not in tables
    assert "chat_session_titles" not in tables
    assert "chat_turns" not in tables
    assert "chat_cancellations" not in tables
    assert "estimated_minutes" not in {column["name"] for column in inspector.get_columns("nodes")}


def test_application_guard_rejects_legacy_revision_and_accepts_head(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'guard.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0001_current_schema_baseline")
    engine = create_engine(database_url)

    with pytest.raises(RuntimeError, match="Database migration required"):
        assert_database_at_head(engine)

    command.upgrade(config, "head")
    assert_database_at_head(engine)
    engine.dispose()


def test_chat_context_backfill_preserves_text_and_only_adopts_complete_isolated_pairs(tmp_path):
    import sqlalchemy as sa

    database_url = f"sqlite:///{tmp_path / 'chat-context-backfill.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0009_split_ai_avatar_presets")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, avatar_url) VALUES "
                "(1, 'first', 'first@example.test', 'hash', '/avatars/study/boy-read.webp'), "
                "(2, 'second', 'second@example.test', 'hash', '/avatars/study/boy-read.webp')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO topics (id, user_id, title) VALUES (1, 1, 'Scoped A'), (2, 1, 'Scoped B')"
            )
        )
        messages = sa.Table("chat_messages", sa.MetaData(), autoload_with=connection)
        rows = []

        def message(
            identifier,
            role,
            content,
            *,
            name="same-name",
            user_id=1,
            topic_id=None,
            node_key="normal",
            mode="normal",
            status=None,
            message_type="chat",
        ):
            rows.append(
                dict(
                    id=identifier,
                    user_id=user_id,
                    topic_id=topic_id,
                    session_id=name,
                    node_key=node_key,
                    role=role,
                    content=content,
                    mode=mode,
                    message_type=message_type,
                    metadata_json={"status": status} if status else None,
                )
            )

        message(1, "user", "complete question")
        message(2, "ai", "complete answer")
        message(3, "user", "unanswered question")
        message(4, "ai", "", status="complete")
        message(5, "user", "failed question")
        message(6, "ai", "failed partial", status="failed")
        message(7, "ai", "orphan answer")
        message(10, "user", "scope A question", name="mixed", topic_id=1, mode="socratic")
        message(11, "ai", "scope A answer", name="mixed", topic_id=1, mode="socratic")
        message(12, "user", "scope B question", name="mixed", topic_id=2, mode="socratic")
        message(13, "ai", "scope B answer", name="mixed", topic_id=2, mode="socratic")
        message(20, "user", "other user question", user_id=2)
        message(21, "ai", "other user answer", user_id=2)
        message(30, "user", "", name="overview", topic_id=1, mode="socratic", node_key="Scoped A")
        message(
            31,
            "ai",
            "topic overview",
            name="overview",
            topic_id=1,
            mode="socratic",
            node_key="Scoped A",
        )
        message(32, "user", "", name="overview", topic_id=1, mode="socratic", node_key="node-A")
        message(
            33,
            "ai",
            "node overview",
            name="overview",
            topic_id=1,
            mode="socratic",
            node_key="node-A",
        )
        message(
            40,
            "ai",
            "structured onboarding",
            topic_id=2,
            mode="socratic",
            message_type="agent_step",
        )
        connection.execute(messages.insert(), rows)
        before = dict(connection.execute(sa.select(messages.c.id, messages.c.content)).all())

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert (
            dict(connection.execute(text("SELECT id, content FROM chat_messages")).all()) == before
        )
        assert connection.execute(
            text("SELECT user_id, session_id FROM chat_sessions ORDER BY user_id, session_id")
        ).all() == [(1, "overview"), (1, "same-name"), (2, "same-name")]
        turns = connection.execute(
            text(
                "SELECT user_message_id, ai_message_id, status, kind FROM chat_turns ORDER BY user_message_id"
            )
        ).all()
        assert turns == [
            (1, 2, "complete", "qa"),
            (20, 21, "complete", "qa"),
            (30, 31, "complete", "topic_overview"),
            (32, 33, "complete", "node_overview"),
        ]
        assert (
            connection.scalar(
                text("SELECT count(*) FROM chat_sessions WHERE active_request_id IS NOT NULL")
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM chat_sessions WHERE summary_json IS NOT NULL")
            )
            == 0
        )
        metadata = sa.Table("chat_messages", sa.MetaData(), autoload_with=connection)
        restored = connection.execute(
            sa.select(metadata.c.metadata_json).where(metadata.c.id == 31)
        ).scalar_one()
        assert restored["user_message_id"] == 30
        assert restored["kind"] == "topic_overview"
    engine.dispose()


def test_chat_context_backfill_pairs_messages_across_keyset_batch_boundaries(tmp_path):
    import sqlalchemy as sa

    database_url = f"sqlite:///{tmp_path / 'chat-backfill-batches.sqlite'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0009_split_ai_avatar_presets")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, avatar_url) VALUES "
                "(1, 'batch-user', 'batch@example.test', 'hash', '/avatars/study/boy-read.webp')"
            )
        )
        messages = sa.Table("chat_messages", sa.MetaData(), autoload_with=connection)
        shared = dict(
            user_id=1,
            session_id="long-history",
            topic_id=None,
            node_key="normal",
            mode="normal",
            message_type="chat",
            metadata_json={"status": "complete"},
        )
        # The leading orphan shifts questions onto the last row of each 256-row
        # page, so a complete pair must survive the read/write page transition.
        rows = [{**shared, "id": 1, "role": "ai", "content": "orphan"}]
        for index in range(300):
            rows.extend(
                [
                    {**shared, "id": 2 * index + 2, "role": "user", "content": f"question {index}"},
                    {**shared, "id": 2 * index + 3, "role": "ai", "content": f"answer {index}"},
                ]
            )
        connection.execute(messages.insert(), rows)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        restored_pairs = connection.execute(
            text("SELECT user_message_id, ai_message_id FROM chat_turns ORDER BY user_message_id")
        ).all()
        assert restored_pairs == [(2 * index + 2, 2 * index + 3) for index in range(300)]
        assert (256, 257) in restored_pairs
        assert (512, 513) in restored_pairs
        assert connection.scalar(text("SELECT count(*) FROM chat_messages")) == 601
        assert connection.scalar(text("SELECT count(*) FROM chat_sessions")) == 1
    engine.dispose()
