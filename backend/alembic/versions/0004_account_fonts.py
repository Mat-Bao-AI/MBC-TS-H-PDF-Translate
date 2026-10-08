"""account settings + translated-text fonts: display_name, default_font, files.font*, email_tokens.new_email

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default điền giá trị cho dòng đã có (SQLite không nhận NOT NULL không default khi ADD COLUMN);
    # dòng mới lấy default phía Python trong models.py.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("display_name", sa.String(50), nullable=True))
        batch.add_column(sa.Column("default_font", sa.String(8), nullable=False, server_default="auto"))
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("font", sa.String(8), nullable=False, server_default="auto"))
        batch.add_column(sa.Column("font_used", sa.String(8), nullable=True))
        batch.add_column(sa.Column("rebuild_font", sa.String(8), nullable=True))
        batch.add_column(sa.Column("rebuild_error", sa.String(1000), nullable=False, server_default=""))
    with op.batch_alter_table("email_tokens") as batch:
        batch.add_column(sa.Column("new_email", sa.String(254), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("email_tokens") as batch:
        batch.drop_column("new_email")
    with op.batch_alter_table("files") as batch:
        batch.drop_column("rebuild_error")
        batch.drop_column("rebuild_font")
        batch.drop_column("font_used")
        batch.drop_column("font")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("default_font")
        batch.drop_column("display_name")
