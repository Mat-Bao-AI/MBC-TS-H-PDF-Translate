"""instance_settings.site_url — site address recorded at /setup (used only for links in mail)

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = chưa biết: instance cài từ trước (APP_BASE_URL còn bắt buộc) hoặc /setup chạy trên http ngoài localhost.
    with op.batch_alter_table("instance_settings") as batch:
        batch.add_column(sa.Column("site_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("instance_settings") as batch:
        batch.drop_column("site_url")
