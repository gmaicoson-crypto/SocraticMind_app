"""Add persistent Learning Agent workflows, plans, memories, and mastery evidence."""

from alembic import op
import sqlalchemy as sa


revision = "0002_p0_learning_agent"
down_revision = "0001_current_schema_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.add_column(
            sa.Column("estimated_minutes", sa.Integer(), server_default="30", nullable=False)
        )
        batch_op.add_column(sa.Column("mastery_source", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("mastery_confidence", sa.Float(), nullable=True))
    op.execute("UPDATE nodes SET mastery_source = 'legacy' WHERE state = 'mastered'")

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(
            sa.Column("message_type", sa.String(length=30), server_default="chat", nullable=False)
        )
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("run_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("token_usage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_user_status", "agent_runs", ["user_id", "status"])
    op.create_index("ix_agent_runs_topic_id", "agent_runs", ["topic_id"])

    op.create_table(
        "learner_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("content", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learner_memories_user_topic_kind",
        "learner_memories",
        ["user_id", "topic_id", "kind"],
    )

    op.create_table(
        "study_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("goal", sa.String(length=500), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("outcome_type", sa.String(length=30), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("estimated_end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_request_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", name="uq_study_plans_topic_id"),
    )
    op.create_index("ix_study_plans_user_status", "study_plans", ["user_id", "status"])

    op.create_table(
        "study_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("day_order", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["study_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "node_id", "scheduled_date", name="uq_plan_node_date"),
    )
    op.create_index(
        "ix_plan_items_plan_date_status",
        "study_plan_items",
        ["plan_id", "scheduled_date", "status"],
    )
    op.create_index("ix_plan_items_node_id", "study_plan_items", ["node_id"])

    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("questions_json", sa.JSON(), nullable=False),
        sa.Column("answers_json", sa.JSON(), nullable=False),
        sa.Column("rubrics_json", sa.JSON(), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=True),
        sa.Column("evaluation_confidence", sa.Float(), nullable=True),
        sa.Column("critical_misconception", sa.Boolean(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_assessment_attempts_run_id"),
    )
    op.create_index(
        "ix_assessment_user_node_status",
        "assessment_attempts",
        ["user_id", "node_id", "status"],
    )

    op.create_table(
        "mastery_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("from_state", sa.String(length=20), nullable=False),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=True),
        sa.Column("reverts_event_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessment_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reverts_event_id"], ["mastery_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "request_id", name="uq_mastery_user_request"),
    )
    op.create_index("ix_mastery_events_node_created", "mastery_events", ["node_id", "created_at"])


def downgrade() -> None:
    op.drop_table("mastery_events")
    op.drop_table("assessment_attempts")
    op.drop_table("study_plan_items")
    op.drop_table("study_plans")
    op.drop_table("learner_memories")
    op.drop_table("agent_runs")
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("message_type")
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.drop_column("mastery_confidence")
        batch_op.drop_column("mastery_source")
        batch_op.drop_column("estimated_minutes")
