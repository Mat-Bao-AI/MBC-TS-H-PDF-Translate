import logging
import smtplib
import ssl
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.auth.mailer import LogMailer, Mail, SmtpMailer, deliver, mailer_from_settings
from app.db import make_engine, make_session_factory, upgrade_db
from app.system.mail import deliver_later, resolve_mail
from app.system.store import instance_row, seal_smtp_password
from helpers import MemoryMailer, bare_client, fake_smtp


@contextmanager
def db_session(settings):
    """Phiên trên DB đã migrate; engine được dispose khi ra (không để kết nối SQLite mồ côi → ResourceWarning)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_db(settings.database_url)
    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as db:
            yield db
    finally:
        engine.dispose()


def save_smtp_row(db, *, security="starttls", port=587, username="u", password_enc=None) -> None:
    row = instance_row(db)
    row.smtp_host, row.smtp_port, row.smtp_security, row.smtp_from = "db.example.com", port, security, "db@example.com"
    row.smtp_username, row.smtp_password_enc = username, password_enc
    db.commit()


def test_log_mailer_prints_the_link(caplog):
    with caplog.at_level(logging.WARNING, logger="mailer"):
        LogMailer().send(Mail("an@example.com", "Chủ đề", "Link: https://x/verify-email?token=abc"))
    assert "to=an@example.com" in caplog.text
    assert "verify-email?token=abc" in caplog.text


def test_settings_choose_the_mailer(settings):
    assert isinstance(mailer_from_settings(settings), LogMailer)
    smtp = mailer_from_settings(replace(settings, smtp_host="smtp.example.com", smtp_from="no-reply@example.com", smtp_security="ssl"))
    assert isinstance(smtp, SmtpMailer) and (smtp.host, smtp.security) == ("smtp.example.com", "ssl")


@pytest.mark.parametrize(("security", "transport", "port", "starttls"), [
    ("starttls", "SMTP", 587, True), ("ssl", "SMTP_SSL", 465, False), ("none", "SMTP", 25, False),
])
def test_security_mode_picks_the_transport(monkeypatch, security, transport, port, starttls):
    events = fake_smtp(monkeypatch)
    SmtpMailer("smtp.example.com", port, "u", "p", "PDF <no-reply@example.com>", security).send(Mail("an@example.com", "Chủ đề", "Nội dung"))
    assert events[0] == (transport, "smtp.example.com", port, 15)
    assert (("starttls",) in events) is starttls
    assert ("login", "u", "p") in events
    assert ("send", "an@example.com", "Chủ đề", "PDF <no-reply@example.com>") in events and events[-1] == ("quit",)


def test_deliver_swallows_smtp_errors(caplog):
    class Broken:
        def send(self, mail):
            raise OSError("smtp down")

    deliver(Broken(), Mail("an@example.com", "s", "b"))
    assert "smtp down" in caplog.text


def test_smtp_password_stays_out_of_repr():
    mailer = SmtpMailer("smtp.example.com", 587, "u", "mat-khau-smtp-bi-mat", "no-reply@example.com", "starttls")
    assert "mat-khau-smtp-bi-mat" not in repr(mailer)


def test_resolution_order_env_then_dev_log_then_log(settings):
    with db_session(settings) as db:
        env = replace(settings, smtp_host="env.example.com", smtp_from="env@example.com")
        setup = resolve_mail(db, env, None)
        assert (setup.source, setup.enabled) == ("env", True) and isinstance(setup.mailer, SmtpMailer)
        setup = resolve_mail(db, replace(settings, mail_dev_log=True), None)
        assert (setup.source, setup.enabled, type(setup.mailer)) == ("dev_log", True, LogMailer)
        setup = resolve_mail(db, settings, None)
        assert (setup.source, setup.enabled, type(setup.mailer)) == ("none", False, LogMailer)


def test_a_transport_without_a_site_address_is_configured_but_not_enabled(settings):
    # Đóng an toàn: có đường gửi mà không biết địa chỉ trang (không APP_BASE_URL, /setup chưa ghi) → không phát link nào.
    with db_session(settings) as db:
        for unset in (replace(settings, app_base_url=None, smtp_host="env.example.com", smtp_from="env@example.com"),
                      replace(settings, app_base_url=None, mail_dev_log=True)):
            setup = resolve_mail(db, unset, None)
            assert (setup.configured, setup.enabled, setup.site_url) == (True, False, None)
        setup = resolve_mail(db, replace(settings, app_base_url=None), MemoryMailer())
        assert (setup.configured, setup.enabled) == (True, False)
        instance_row(db).site_url = "https://ghi-luc-cai-dat.example"
        db.commit()
        setup = resolve_mail(db, replace(settings, app_base_url=None, mail_dev_log=True), None)
        assert (setup.enabled, setup.site_url) == (True, "https://ghi-luc-cai-dat.example")
        setup = resolve_mail(db, replace(settings, app_base_url=None), None)  # không đường gửi: vẫn tắt như trước
        assert (setup.configured, setup.enabled) == (False, False)


def test_db_settings_beat_env_and_apply_without_restart(settings, monkeypatch):
    events = fake_smtp(monkeypatch)
    env = replace(settings, smtp_host="env.example.com", smtp_from="env@example.com")
    with bare_client(env) as client:  # không tiêm mailer: thư đi qua smtplib (giả)
        with client.app.state.session_factory() as db:
            row = instance_row(db)
            row.smtp_host, row.smtp_port, row.smtp_security, row.smtp_from = "db.example.com", 2525, "none", "db@example.com"
            db.commit()
        assert client.post("/api/auth/register", json={"email": "mot@example.com", "password": "mat-khau-8"}).status_code == 202
        assert events[0][:3] == ("SMTP", "db.example.com", 2525) and ("starttls",) not in events
        assert ("send", "mot@example.com", "Xác nhận email cho PDF Translate", "db@example.com") in events
        events.clear()
        with client.app.state.session_factory() as db:
            instance_row(db).smtp_host = None  # "Xoá cấu hình, quay về biến môi trường"
            db.commit()
        assert client.post("/api/auth/register", json={"email": "hai@example.com", "password": "mat-khau-8"}).status_code == 202
        assert events[0][:3] == ("SMTP", "env.example.com", 587) and ("starttls",) in events


def test_an_injected_mailer_replaces_the_transport_and_counts_as_configured(settings):
    memory = MemoryMailer()
    with db_session(settings) as db:
        setup = resolve_mail(db, settings, memory)
        assert setup.mailer is memory and (setup.source, setup.enabled) == ("dev_log", True)
        instance_row(db).smtp_host = "db.example.com"
        db.commit()
        setup = resolve_mail(db, settings, memory)
        assert setup.mailer is memory and setup.source == "settings"  # dòng nguồn vẫn nói sự thật, thư vẫn vào mailer tiêm


def test_an_unreadable_saved_password_means_no_login(settings, monkeypatch):
    events = fake_smtp(monkeypatch)
    with db_session(settings) as db:
        save_smtp_row(db, password_enc=seal_smtp_password("x" * 32, "mat-khau-cu"))  # SECRET_KEY đã đổi
        resolve_mail(db, settings, None).mailer.send(Mail("an@example.com", "Chủ đề", "Nội dung"))
    assert [event for event in events if event[0] == "login"] == []  # không AUTH với mật khẩu rỗng
    assert ("send", "an@example.com", "Chủ đề", "db@example.com") in events


def test_a_saved_password_that_opens_is_used_to_log_in(settings, monkeypatch):
    events = fake_smtp(monkeypatch)
    with db_session(settings) as db:
        save_smtp_row(db, password_enc=seal_smtp_password(settings.secret_key, "mat-khau-db"))
        resolve_mail(db, settings, None).mailer.send(Mail("an@example.com", "Chủ đề", "Nội dung"))
    assert events[0] == ("SMTP", "db.example.com", 587, 15) and ("starttls",) in events
    assert ("login", "u", "mat-khau-db") in events


@pytest.mark.parametrize(("security", "transport", "port"), [("ssl", "SMTP_SSL", 465), ("starttls", "SMTP", 587)])
def test_a_saved_row_without_a_port_uses_the_default_port_of_its_security(settings, monkeypatch, security, transport, port):
    events = fake_smtp(monkeypatch)
    with db_session(settings) as db:
        save_smtp_row(db, security=security, port=None, username=None)
        mailer = resolve_mail(db, settings, None).mailer
        mailer.send(Mail("an@example.com", "Chủ đề", "Nội dung"))
    assert mailer.port == port and events[0] == (transport, "db.example.com", port, 15)


@pytest.mark.parametrize(("security", "step"), [("ssl", "SMTP_SSL"), ("starttls", "starttls")])
def test_tls_verifies_the_certificate_and_the_hostname(monkeypatch, security, step):
    events = fake_smtp(monkeypatch)
    SmtpMailer("smtp.example.com", 465, "u", "p", "no-reply@example.com", security).send(Mail("an@example.com", "s", "b"))
    [(where, context)] = events.contexts  # không có context = Python 3.12 không kiểm chứng chỉ → MITM đọc được mật khẩu
    assert where == step and isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED


def test_an_unknown_security_mode_fails_closed(monkeypatch):
    events = fake_smtp(monkeypatch)
    with pytest.raises(ValueError, match="security"):
        SmtpMailer("smtp.example.com", 587, "u", "p", "no-reply@example.com", "tls").send(Mail("an@example.com", "s", "b"))
    assert events == []  # không mở kết nối nào — càng không gửi mật khẩu qua kênh không mã hoá


def test_a_failed_smtp_send_logs_the_server_but_never_the_password(monkeypatch, caplog):
    events = fake_smtp(monkeypatch)
    events.raise_on_login = smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")
    deliver(SmtpMailer("smtp.example.com", 2525, "u", "mat-khau-smtp-bi-mat", "no-reply@example.com"), Mail("an@example.com", "s", "b"))
    assert "an@example.com" in caplog.text and "smtp.example.com:2525" in caplog.text
    assert "mat-khau-smtp-bi-mat" not in caplog.text


def test_deliver_later_logs_once_when_the_mail_settings_cannot_be_read(settings, caplog):
    def broken_session():
        raise RuntimeError("database is locked")

    memory = MemoryMailer()
    app = SimpleNamespace(state=SimpleNamespace(session_factory=broken_session, settings=settings, injected_mailer=memory))
    deliver_later(app, Mail("an@example.com", "s", "b"))  # không ném ra BackgroundTask
    assert memory.sent == [] and len(caplog.records) == 1
    assert "an@example.com" in caplog.text and "database is locked" in caplog.text
