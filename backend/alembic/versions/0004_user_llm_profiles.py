"""add user-owned LLM profiles

Revision ID: 0004_user_llm_profiles
Revises: 0003_p0_query_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "0004_user_llm_profiles"
down_revision: str | None = "0003_p0_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_llm_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "config_id", name="uq_user_llm_profiles_user_config"),
    )
    op.create_index("ix_user_llm_profiles_user_id", "user_llm_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_llm_profiles_user_id", table_name="user_llm_profiles")
    op.drop_table("user_llm_profiles")
