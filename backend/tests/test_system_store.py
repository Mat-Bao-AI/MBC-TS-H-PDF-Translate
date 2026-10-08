from sqlalchemy import text

from app.db import make_engine, make_session_factory, upgrade_db
from app.models import InstanceSettings
from app.providers.crypto import open_sealed
from app.system import store

SECRET = "s" * 32


def test_smtp_password_round_trips_with_the_same_secret_key():
    token = store.seal_smtp_password(SECRET, "mat-khau-smtp")
    assert "mat-khau-smtp" not in token
    assert store.open_smtp_password(SECRET, token) == "mat-khau-smtp"


def test_a_rotated_secret_key_or_no_token_opens_to_none():
    token = store.seal_smtp_password(SECRET, "mat-khau-smtp")
    assert store.open_smtp_password("t" * 32, token) is None  # SECRET_KEY đã đổi = password_status "unreadable"
    assert store.open_smtp_password(SECRET, None) is None  # chưa lưu mật khẩu


def test_the_smtp_password_uses_its_own_pinned_key_domain():
    # Đổi một trong hai hằng số = mọi mật khẩu SMTP đã lưu thành "unreadable": giá trị bị khoá ở đây.
    assert (store.SMTP_INFO, store.SMTP_AAD) == (b"instance-settings/v1", b"instance:smtp")
    token = store.seal_smtp_password(SECRET, "mat-khau-smtp")
    assert open_sealed(SECRET, token, info=store.SMTP_INFO, aad=store.SMTP_AAD) == "mat-khau-smtp"


def test_instance_row_reinserts_a_missing_row_with_defaults(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_db(settings.database_url)
    engine = make_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM instance_settings"))
    with make_session_factory(engine)() as db:
        row = store.instance_row(db)
        assert (row.id, row.smtp_host, row.registration_open, row.max_pending_per_user, row.setup_completed_at) == (
            1, None, True, None, None)
        assert row.updated_at is not None
    with make_session_factory(engine)() as db:  # đã ghi xuống DB, không chỉ nằm trong phiên
        assert db.query(InstanceSettings).count() == 1 and db.get(InstanceSettings, 1) is not None
    engine.dispose()
