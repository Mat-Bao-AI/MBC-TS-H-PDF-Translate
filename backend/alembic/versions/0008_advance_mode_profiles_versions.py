"""advance mode: translation profiles, config snapshots, file versions, max_versions

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default điền giá trị cho dòng đã có (SQLite không nhận NOT NULL không default khi ADD COLUMN).
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("advance_mode", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("default_profile", sa.String(40), nullable=True))
    op.create_table(
        "translation_profiles",
        sa.Column("id", sa.String(12), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("fidelity", sa.String(8), nullable=False),
        sa.Column("tone", sa.String(12), nullable=False),
        sa.Column("audience", sa.String(8), nullable=False),
        sa.Column("terms", sa.String(24), nullable=False),
        sa.Column("proper_names", sa.String(8), nullable=False),
        sa.Column("numbers", sa.String(17), nullable=False),
        sa.Column("dates", sa.String(17), nullable=False),
        sa.Column("abbreviations", sa.String(6), nullable=False),
        sa.Column("custom_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_translation_profiles_user_id", "translation_profiles", ["user_id"])
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("config", sa.Text(), nullable=True))
        batch.add_column(sa.Column("retranslate_config", sa.Text(), nullable=True))
        batch.add_column(sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "file_versions",
        sa.Column("id", sa.String(12), primary_key=True),
        sa.Column("file_id", sa.String(12), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("font", sa.String(8), nullable=False),
        sa.Column("font_used", sa.String(8), nullable=True),
        sa.Column("config", sa.Text(), nullable=True),
        sa.Column("output_name", sa.String(255), nullable=False),
        sa.Column("untranslated", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_file_versions_file_version", "file_versions", ["file_id", "version_no"])
    with op.batch_alter_table("instance_settings") as batch:
        batch.add_column(sa.Column("max_versions", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("instance_settings") as batch:
        batch.drop_column("max_versions")
    op.drop_index("ix_file_versions_file_version", table_name="file_versions")
    op.drop_table("file_versions")
    with op.batch_alter_table("files") as batch:
        batch.drop_column("version_no")
        batch.drop_column("retranslate_config")
        batch.drop_column("config")
    op.drop_index("ix_translation_profiles_user_id", table_name="translation_profiles")
    op.drop_table("translation_profiles")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("default_profile")
        batch.drop_column("advance_mode")
