"""Replace legacy color avatars with random study portraits.

Revision ID: 0008_random_user_avatars
Revises: 0007_avatar_presets
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_random_user_avatars"
down_revision: str | None = "0007_avatar_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_AVATAR_NAMES = (
    "girl-journal",
    "boy-sketch",
    "girl-poetry",
    "boy-write",
    "girl-botany",
    "boy-insects",
    "boy-read",
    "boy-calligraphy",
    "boy-astronomy",
    "girl-globe",
    "boy-geometry",
    "girl-read",
    "boy-math",
    "girl-handwriting",
    "boy-atlas",
    "girl-music",
    "girl-butterfly",
    "girl-write",
    "girl-flashcards",
    "boy-dictionary",
)
USER_AVATARS = tuple(f"/avatars/study/{name}.webp" for name in USER_AVATAR_NAMES)


def upgrade() -> None:
    connection = op.get_bind()
    ids = (
        connection.execute(sa.text("SELECT id FROM users WHERE avatar_url IS NULL")).scalars().all()
    )
    for user_id in ids:
        connection.execute(
            sa.text("UPDATE users SET avatar_url = :avatar_url WHERE id = :user_id"),
            {"avatar_url": secrets.choice(USER_AVATARS), "user_id": user_id},
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "avatar_url",
            existing_type=sa.String(length=500),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "avatar_url",
            existing_type=sa.String(length=500),
            nullable=True,
            server_default="/avatars/study/boy-read.webp",
        )
