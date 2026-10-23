"""remove redundant user LLM config ID

Revision ID: 0005_remove_llm_config_id
Revises: 0004_user_llm_profiles
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_remove_llm_config_id"
down_revision: str | None = "0004_user_llm_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_llm_profiles") as batch:
        batch.drop_constraint("uq_user_llm_profiles_user_config", type_="unique")
        batch.drop_column("config_id")


def downgrade() -> None:
    with op.batch_alter_table("user_llm_profiles") as batch:
        batch.add_column(sa.Column("config_id", sa.String(length=64), nullable=True))
    op.execute("UPDATE user_llm_profiles SET config_id = id")
    with op.batch_alter_table("user_llm_profiles") as batch:
        batch.alter_column("config_id", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint("uq_user_llm_profiles_user_config", ["user_id", "config_id"])
