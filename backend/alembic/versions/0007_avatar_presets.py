"""Add default portrait choices for users and AI.

Revision ID: 0007_avatar_presets
Revises: 0006_archive_deleted_progress
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_avatar_presets"
down_revision: str | None = "0006_archive_deleted_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "ai_avatar_url",
                sa.String(length=500),
                nullable=False,
                server_default="/avatars/AI/AI-male-1.webp",
            )
        )
        batch_op.alter_column(
            "avatar_url",
            existing_type=sa.String(length=500),
            server_default="/avatars/study/boy-read.webp",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "avatar_url", existing_type=sa.String(length=500), server_default=None
        )
        batch_op.drop_column("ai_avatar_url")
