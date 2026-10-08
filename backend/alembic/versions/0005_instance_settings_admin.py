"""admin flag, single-row instance settings, retranslate columns

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"))
    # Instance đang có người dùng (demo): người tạo sớm nhất (hoà → id nhỏ nhất) thành quản trị viên (spec §2).
    op.execute("UPDATE users SET is_admin = 1 WHERE id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)")
    op.create_table(
        "instance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("smtp_host", sa.String(253), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_security", sa.String(8), nullable=True),
        sa.Column("smtp_username", sa.String(254), nullable=True),
        sa.Column("smtp_password_enc", sa.Text(), nullable=True),
        sa.Column("smtp_from", sa.String(254), nullable=True),
        sa.Column("registration_open", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("max_pending_per_user", sa.Integer(), nullable=True),
        sa.Column("setup_completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_instance_settings_single_row"),
    )
    # Đúng một dòng id=1. Đã có người dùng = đã "cài đặt" từ trước (CURRENT_TIMESTAMP của SQLite là UTC, cùng quy ước utcnow()).
    op.execute(
        "INSERT INTO instance_settings (id, registration_open, max_pending_per_user, setup_completed_at, updated_at) "
        "SELECT 1, 1, NULL, CASE WHEN EXISTS (SELECT 1 FROM users) THEN CURRENT_TIMESTAMP ELSE NULL END, CURRENT_TIMESTAMP"
    )
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("retranslate_language", sa.String(8), nullable=True))
        batch.add_column(sa.Column("retranslate_engine", sa.String(20), nullable=True))
        batch.add_column(sa.Column("retranslate_model", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("files") as batch:
        batch.drop_column("retranslate_model")
        batch.drop_column("retranslate_engine")
        batch.drop_column("retranslate_language")
    op.drop_table("instance_settings")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_admin")
