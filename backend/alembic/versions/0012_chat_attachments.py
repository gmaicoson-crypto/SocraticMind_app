"""Private chat attachments, independent cleanup jobs and explicit image capabilities."""

from alembic import op
import sqlalchemy as sa

revision = "0012_chat_attachments"
down_revision = "0011_web_search_quotas"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("client_upload_id", sa.String(100), nullable=False),
        sa.Column("draft_session_id", sa.String(100), nullable=False),
        sa.Column("session_id", sa.String(100)),
        sa.Column("topic_id", sa.Integer()),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("preview_key", sa.String(255)),
        sa.Column("image_key", sa.String(255)),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("pages", sa.Integer()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("coverage", sa.JSON()),
        sa.Column("accepted_coverage", sa.JSON()),
        sa.Column("accepted_revision", sa.Integer()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "uq_attachment_upload", "attachments", ["user_id", "client_upload_id"], unique=True
    )
    op.create_index("ix_attachment_work", "attachments", ["status", "next_retry_at"])
    op.create_index("ix_attachment_scope", "attachments", ["user_id", "session_id"])
    op.create_index("ix_attachment_expiry", "attachments", ["status", "expires_at"])
    op.create_table(
        "message_attachments",
        sa.Column(
            "user_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "attachment_id",
            sa.String(36),
            sa.ForeignKey("attachments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("accepted_coverage", sa.JSON()),
    )
    op.create_index(
        "uq_message_attachment_position",
        "message_attachments",
        ["user_message_id", "position"],
        unique=True,
    )
    op.create_index("uq_attachment_message", "message_attachments", ["attachment_id"], unique=True)
    op.create_table(
        "attachment_chunks",
        sa.Column(
            "attachment_id",
            sa.String(36),
            sa.ForeignKey("attachments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("chunk_id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("block_type", sa.String(30), nullable=False),
        sa.Column("title_path", sa.JSON(), nullable=False),
        sa.Column("asset_refs", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_attachment_chunk_order", "attachment_chunks", ["attachment_id", "revision", "position"]
    )
    op.create_table(
        "attachment_cleanup",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storage_prefix", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    slots = op.create_table(
        "attachment_worker_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(slots, [{"id": 1}, {"id": 2}])
    op.add_column("chat_turns", sa.Column("preparation_json", sa.JSON()))
    op.add_column(
        "user_llm_profiles",
        sa.Column("image_input", sa.String(16), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "user_llm_profiles",
        sa.Column("max_images", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "user_llm_profiles",
        sa.Column("max_image_bytes", sa.Integer(), nullable=False, server_default="10485760"),
    )
    op.add_column("user_llm_profiles", sa.Column("vision_token_budget", sa.Integer()))


def downgrade():
    for name in ("vision_token_budget", "max_image_bytes", "max_images", "image_input"):
        op.drop_column("user_llm_profiles", name)
    op.drop_column("chat_turns", "preparation_json")
    for name in (
        "attachment_worker_slots",
        "attachment_cleanup",
        "attachment_chunks",
        "message_attachments",
        "attachments",
    ):
        op.drop_table(name)
