"""Retain learning progress when source content is deleted.

Revision ID: 0006_archive_deleted_progress
Revises: 0005_remove_llm_config_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_archive_deleted_progress"
down_revision: str | None = "0005_remove_llm_config_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "archived_chat_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_archived_chat_user_day", "archived_chat_activity", ["user_id", "day"])
    op.create_index("ix_archived_chat_user_hour", "archived_chat_activity", ["user_id", "hour"])
    op.create_table(
        "archived_mastery",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("topic_title", sa.String(length=200), nullable=False),
        sa.Column("mastered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_archived_mastery_user_time", "archived_mastery", ["user_id", "mastered_at"])


def downgrade() -> None:
    op.drop_index("ix_archived_mastery_user_time", table_name="archived_mastery")
    op.drop_table("archived_mastery")
    op.drop_index("ix_archived_chat_user_hour", table_name="archived_chat_activity")
    op.drop_index("ix_archived_chat_user_day", table_name="archived_chat_activity")
    op.drop_table("archived_chat_activity")
