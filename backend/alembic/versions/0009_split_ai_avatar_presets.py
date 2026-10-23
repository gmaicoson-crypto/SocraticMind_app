"""Move AI avatar paths into normal and study groups.

Revision ID: 0009_split_ai_avatar_presets
Revises: 0008_random_user_avatars
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_split_ai_avatar_presets"
down_revision: str | None = "0008_random_user_avatars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    for gender in ("female", "male"):
        for index in range(1, 4):
            name = f"AI-{gender}-{index}.webp"
            connection.execute(
                sa.text("UPDATE users SET ai_avatar_url = :new WHERE ai_avatar_url = :old"),
                {"new": f"/avatars/AI/study/{name}", "old": f"/avatars/AI/{name}"},
            )
    for index in range(1, 7):
        name = f"AI_normal{f'_{index}' if index > 1 else ''}.webp"
        connection.execute(
            sa.text("UPDATE users SET ai_avatar_url = :new WHERE ai_avatar_url = :old"),
            {"new": f"/avatars/AI/normal/{name}", "old": f"/avatars/AI/{name}"},
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "ai_avatar_url",
            existing_type=sa.String(length=500),
            server_default="/avatars/AI/study/AI-male-1.webp",
        )


def downgrade() -> None:
    connection = op.get_bind()
    for gender in ("female", "male"):
        for index in range(1, 4):
            name = f"AI-{gender}-{index}.webp"
            connection.execute(
                sa.text("UPDATE users SET ai_avatar_url = :new WHERE ai_avatar_url = :old"),
                {"new": f"/avatars/AI/{name}", "old": f"/avatars/AI/study/{name}"},
            )
    for index in range(1, 7):
        name = f"AI_normal{f'_{index}' if index > 1 else ''}.webp"
        connection.execute(
            sa.text("UPDATE users SET ai_avatar_url = :new WHERE ai_avatar_url = :old"),
            {"new": f"/avatars/AI/{name}", "old": f"/avatars/AI/normal/{name}"},
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "ai_avatar_url",
            existing_type=sa.String(length=500),
            server_default="/avatars/AI/AI-male-1.webp",
        )
