"""email token nonce: tự đăng nhập sau xác thực chỉ ở trình duyệt đã xin link

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL cho token cũ: xác thực vẫn được, chỉ là không tự đăng nhập.
    op.add_column("email_tokens", sa.Column("nonce_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("email_tokens") as batch:
        batch.drop_column("nonce_hash")
