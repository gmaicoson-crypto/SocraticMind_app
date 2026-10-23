"""Persist AI and manual session titles independently of learning topics."""

from alembic import op
import sqlalchemy as sa

revision = "0013_chat_session_titles"
down_revision = "0012_chat_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_session_titles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("title", sa.String(40)),
        sa.Column("source_text", sa.Text()),
        sa.Column("model_id", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "uq_chat_session_titles_user_session",
        "chat_session_titles",
        ["user_id", "session_id"],
        unique=True,
    )
    op.create_index(
        "ix_chat_session_titles_work", "chat_session_titles", ["status", "next_retry_at"]
    )


def downgrade():
    op.drop_table("chat_session_titles")
