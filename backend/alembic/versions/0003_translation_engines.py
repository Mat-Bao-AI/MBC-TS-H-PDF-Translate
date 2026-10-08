"""translation engines: api_credentials + engine/model/stage columns

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(12), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("hint", sa.String(8), nullable=False),
        sa.Column("models", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_api_credentials_user_provider"),
    )
    op.create_index("ix_api_credentials_user_id", "api_credentials", ["user_id"])
    # server_default điền giá trị cho dòng đã có (SQLite không nhận NOT NULL không default khi ADD COLUMN);
    # dòng mới lấy default phía Python trong models.py.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("default_engine", sa.String(20), nullable=False, server_default="google_free"))
        batch.add_column(sa.Column("default_model", sa.String(64), nullable=True))
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("engine", sa.String(20), nullable=False, server_default="google_free"))
        batch.add_column(sa.Column("model", sa.String(64), nullable=True))
        batch.add_column(sa.Column("stage", sa.String(12), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("files") as batch:
        batch.drop_column("stage")
        batch.drop_column("model")
        batch.drop_column("engine")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("default_model")
        batch.drop_column("default_engine")
    op.drop_index("ix_api_credentials_user_id", table_name="api_credentials")
    op.drop_table("api_credentials")
