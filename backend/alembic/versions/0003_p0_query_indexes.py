"""add P0 query indexes

Revision ID: 0003_p0_query_indexes
Revises: 0002_p0_learning_agent
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "0003_p0_query_indexes"
down_revision: str | None = "0002_p0_learning_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    users = sa.table(
        "users",
        sa.column("avatar_grad", sa.String()),
        sa.column("bio", sa.String()),
        sa.column("daily_goal", sa.Integer()),
        sa.column("ai_style", sa.String()),
    )
    op.execute(
        users.update()
        .where(users.c.avatar_grad.is_(None))
        .values(avatar_grad="linear-gradient(135deg,#e8c87a,#d4974a)")
    )
    op.execute(
        users.update().where(users.c.bio.is_(None)).values(bio="每一个问题都是通往掌握的一步")
    )
    op.execute(users.update().where(users.c.daily_goal.is_(None)).values(daily_goal=5))
    op.execute(users.update().where(users.c.ai_style.is_(None)).values(ai_style="标准"))
    op.create_index(
        "ix_chat_user_session_type_id",
        "chat_messages",
        ["user_id", "session_id", "message_type", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_user_session_type_id", table_name="chat_messages")
