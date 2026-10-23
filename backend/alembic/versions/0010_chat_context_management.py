"""Persist chat context summaries, generation leases and idempotent turns."""

from alembic import op
import sqlalchemy as sa
import hashlib
import uuid

revision = "0010_chat_context_management"
down_revision = "0009_split_ai_avatar_presets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_cancellations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "uq_chat_cancellations_user_request",
        "chat_cancellations",
        ["user_id", "request_id"],
        unique=True,
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="CASCADE")),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("content_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("summary_json", sa.JSON()),
        sa.Column("summary_through_turn_id", sa.Integer()),
        sa.Column("summary_source_version", sa.Integer()),
        sa.Column("summary_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("summary_status", sa.String(20), server_default="idle", nullable=False),
        sa.Column("summary_model", sa.String(100)),
        sa.Column("summary_lease_token", sa.String(36)),
        sa.Column("summary_lease_until", sa.DateTime(timezone=True)),
        sa.Column("summary_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary_next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("active_request_id", sa.String(100)),
        sa.Column("generation_lease_token", sa.String(36)),
        sa.Column("generation_lease_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "uq_chat_sessions_user_session", "chat_sessions", ["user_id", "session_id"], unique=True
    )
    op.create_index(
        "ix_chat_sessions_user_topic_updated",
        "chat_sessions",
        ["user_id", "topic_id", "updated_at"],
    )
    op.create_index(
        "ix_chat_sessions_summary_work",
        "chat_sessions",
        ["summary_status", "summary_next_retry_at"],
    )
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chat_session_id",
            sa.Integer(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "user_message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="SET NULL")
        ),
        sa.Column(
            "ai_message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="SET NULL")
        ),
        sa.Column(
            "regenerate_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(20), server_default="generating", nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("node_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(30), server_default="qa", nullable=False),
        sa.Column("generation_token", sa.String(36), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "uq_chat_turns_user_request", "chat_turns", ["user_id", "request_id"], unique=True
    )
    op.create_index(
        "ix_chat_turns_session_status_id", "chat_turns", ["chat_session_id", "status", "id"]
    )
    op.create_index("ix_chat_turns_ai_message", "chat_turns", ["ai_message_id"])
    op.create_index("ix_chat_turns_user_message", "chat_turns", ["user_message_id"])
    _backfill_development_history()


def _backfill_development_history() -> None:
    """Attach unambiguous complete historical pairs without altering their text."""
    connection = op.get_bind()
    metadata = sa.MetaData()
    messages = sa.Table("chat_messages", metadata, autoload_with=connection)
    sessions = sa.Table("chat_sessions", metadata, autoload_with=connection)
    turns = sa.Table("chat_turns", metadata, autoload_with=connection)
    topics = sa.Table("topics", metadata, autoload_with=connection)
    topic_owners = {
        row.id: (row.user_id, row.title)
        for row in connection.execute(sa.select(topics.c.id, topics.c.user_id, topics.c.title))
    }
    grouped_scopes = {}
    for scope in connection.execute(
        sa.select(messages.c.user_id, messages.c.session_id, messages.c.topic_id, messages.c.mode)
        .where(messages.c.message_type == "chat")
        .distinct()
    ):
        grouped_scopes.setdefault((scope.user_id, scope.session_id), []).append(scope)
    for (user_id, session_id), scopes in grouped_scopes.items():
        if len(scopes) != 1:
            # A reused historical name spanning topics must never become one context.
            continue
        scope = scopes[0]
        if scope.mode not in {"normal", "socratic"} or not session_id:
            continue
        if scope.topic_id is not None and (
            scope.topic_id not in topic_owners or topic_owners[scope.topic_id][0] != user_id
        ):
            continue
        session_pk = connection.execute(
            sessions.insert().values(
                user_id=user_id, session_id=session_id, topic_id=scope.topic_id, mode=scope.mode
            )
        ).inserted_primary_key[0]
        question = None
        for answer in _historical_messages(connection, messages, scope):
            if answer["role"] == "user":
                question = answer
                continue
            previous = question
            question = None
            if previous is None or answer["role"] != "ai":
                continue
            question_meta = previous["metadata_json"] or {}
            answer_meta = answer["metadata_json"] or {}
            if (
                not isinstance(question_meta, dict)
                or not isinstance(answer_meta, dict)
                or question_meta.get("status", "complete") != "complete"
                or answer_meta.get("status", "complete") != "complete"
                or previous["node_key"] != answer["node_key"]
                or not (answer["content"] or "").strip()
            ):
                continue
            kind = answer_meta.get("kind", "qa")
            if kind not in {"qa", "node_overview", "topic_overview"}:
                kind = "qa"
            if not (previous["content"] or "").strip() and scope.mode == "socratic":
                title = topic_owners.get(scope.topic_id, (None, None))[1]
                kind = "topic_overview" if answer["node_key"] == title else "node_overview"
            identity = f"migration:{previous['id']}:{answer['id']}"
            connection.execute(
                turns.insert().values(
                    chat_session_id=session_pk,
                    user_id=user_id,
                    request_id=identity,
                    request_fingerprint=hashlib.sha256(identity.encode()).hexdigest(),
                    user_message_id=previous["id"],
                    ai_message_id=answer["id"],
                    status="complete",
                    model_id="legacy-unrecorded",
                    node_key=answer["node_key"],
                    kind=kind,
                    generation_token=str(uuid.uuid4()),
                    source_version=1,
                    created_at=previous["created_at"],
                    finished_at=answer["created_at"],
                )
            )
            connection.execute(
                messages.update()
                .where(messages.c.id == answer["id"])
                .values(
                    metadata_json={
                        **answer_meta,
                        "user_message_id": previous["id"],
                        "node_key": answer["node_key"],
                        "kind": kind,
                    },
                )
            )


def _historical_messages(connection, messages, scope):
    """Close each bounded read before writes, including MySQL unbuffered cursors."""
    last_id = 0
    while True:
        result = connection.execute(
            sa.select(messages)
            .where(
                messages.c.user_id == scope.user_id,
                messages.c.session_id == scope.session_id,
                messages.c.topic_id == scope.topic_id,
                messages.c.mode == scope.mode,
                messages.c.message_type == "chat",
                messages.c.id > last_id,
            )
            .order_by(messages.c.id)
            .limit(256)
        )
        try:
            batch = result.mappings().all()
        finally:
            result.close()
        if not batch:
            return
        last_id = batch[-1]["id"]
        yield from batch


def downgrade() -> None:
    op.drop_table("chat_turns")
    op.drop_table("chat_sessions")
    op.drop_table("chat_cancellations")
