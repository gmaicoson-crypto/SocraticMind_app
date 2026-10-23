"""Reserve daily web-search queries independently of deletable chat messages."""

from alembic import op
import sqlalchemy as sa

revision = "0011_web_search_quotas"
down_revision = "0010_chat_context_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_search_quotas",
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("used_queries", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("web_search_quotas")
