"""versions: restore marker + translated_at; profiles: seeded presets

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("translation_profiles") as batch:
        batch.add_column(sa.Column("preset_slug", sa.String(16), nullable=True))
    # Một dòng gieo cho mỗi (người, mẫu); preset_slug NULL (hồ sơ thường) không va nhau ở SQLite lẫn PostgreSQL.
    op.create_index("uq_translation_profiles_user_preset", "translation_profiles", ["user_id", "preset_slug"], unique=True)
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("profiles_seeded", sa.Boolean(), nullable=False, server_default="0"))
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("restore_version", sa.String(12), nullable=True))
        batch.add_column(sa.Column("restored_from", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("translated_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("file_versions") as batch:
        batch.add_column(sa.Column("restored_from", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("translated_at", sa.DateTime(), nullable=True))
    # Bản dịch hiện tại của tệp đã xong hoàn tất lúc finished_at; tệp lỗi có finished_at nhưng không có bản dịch → để NULL.
    op.execute(sa.text("UPDATE files SET translated_at = finished_at WHERE status = 'done' AND translated_at IS NULL"))


def downgrade() -> None:
    with op.batch_alter_table("file_versions") as batch:
        batch.drop_column("translated_at")
        batch.drop_column("restored_from")
    with op.batch_alter_table("files") as batch:
        batch.drop_column("translated_at")
        batch.drop_column("restored_from")
        batch.drop_column("restore_version")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("profiles_seeded")
    op.drop_index("uq_translation_profiles_user_preset", table_name="translation_profiles")
    with op.batch_alter_table("translation_profiles") as batch:
        batch.drop_column("preset_slug")
