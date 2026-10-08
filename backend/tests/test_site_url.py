"""Địa chỉ trang trong thư: env APP_BASE_URL > địa chỉ ghi lúc /setup > chưa biết; "có thư" = có đường gửi VÀ biết địa chỉ."""

from dataclasses import replace

import pytest
from sqlalchemy import select

from app.models import User
from app.system.service import TEST_SUBJECT
from app.system.store import instance_row, site_url
from helpers import ADMIN_EMAIL, ADMIN_PASSWORD, MemoryMailer, bare_client, fake_smtp, login_admin

PASSWORD = "mat-khau-8"
RECORDED = "https://ghi-luc-cai-dat.example"
NO_MAIL = {"detail": {"code": "mail_not_configured"}}


def record(client, url: str | None) -> None:
    with client.app.state.session_factory() as db:
        instance_row(db).site_url = url
        db.commit()


def link_mails(client, mailer) -> tuple[str, str]:
    """Thư xác nhận (đăng ký email mới) + thư đặt lại mật khẩu (admin có sẵn) → thân hai thư."""
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"email": "moi@example.com", "password": PASSWORD}).status_code == 202
    assert client.post("/api/auth/forgot-password", json={"email": ADMIN_EMAIL}).status_code == 202
    return mailer.last_to("moi@example.com").body, mailer.last_to(ADMIN_EMAIL).body


def test_the_resolver_prefers_env_then_the_recorded_address(settings):
    unset = replace(settings, app_base_url=None)
    with bare_client(settings, seed=False) as client, client.app.state.session_factory() as db:
        assert site_url(db, settings) == ("https://app.test", "env")
        assert site_url(db, unset) == (None, None)
        instance_row(db).site_url = RECORDED
        db.commit()
        assert site_url(db, settings) == ("https://app.test", "env")
        assert site_url(db, unset) == (RECORDED, "setup")


def test_links_use_env_even_when_an_address_was_recorded(client, mailer):
    record(client, RECORDED)
    verify, reset = link_mails(client, mailer)
    assert "https://app.test/verify-email?token=" in verify
    assert "https://app.test/reset-password?token=" in reset
    assert RECORDED not in verify + reset


def test_links_use_the_recorded_address_when_env_is_unset(settings):
    mailer = MemoryMailer()
    with bare_client(settings, mailer, app_base_url=None) as client:
        record(client, RECORDED)
        assert client.get("/api/setup/status").json()["mail_enabled"] is True
        verify, reset = link_mails(client, mailer)
        assert f"{RECORDED}/verify-email?token=" in verify
        assert f"{RECORDED}/reset-password?token=" in reset


def test_every_other_mail_uses_the_recorded_address_too(settings):
    mailer = MemoryMailer()
    with bare_client(settings, mailer, app_base_url=None) as client:
        record(client, RECORDED)
        # Đăng ký lại email đã có tài khoản → thư "Bạn đã có tài khoản" với link đăng nhập + quên mật khẩu.
        assert client.post("/api/auth/register", json={"email": ADMIN_EMAIL, "password": PASSWORD}).status_code == 202
        existing = mailer.last_to(ADMIN_EMAIL).body
        assert f"{RECORDED}/login" in existing and f"{RECORDED}/forgot-password" in existing
        login_admin(client)
        new_password = "mat-khau-moi-9"
        assert client.post("/api/account/password", json={"current_password": ADMIN_PASSWORD,
                                                           "new_password": new_password}).status_code == 204
        assert f"{RECORDED}/forgot-password" in mailer.last_to(ADMIN_EMAIL).body
        assert client.post("/api/account/email", json={"new_email": "moi-cua-admin@example.com",
                                                        "password": new_password}).status_code == 202
        assert f"{RECORDED}/confirm-email?token=" in mailer.last_to("moi-cua-admin@example.com").body


def test_without_a_site_address_mail_counts_as_off_but_the_test_mail_still_goes(settings):
    mailer = MemoryMailer()  # có đường gửi (mailer tiêm = như MAIL_DEV_LOG) nhưng không env, không địa chỉ ghi lúc /setup
    with bare_client(settings, mailer, app_base_url=None) as client:
        assert client.get("/api/setup/status").json()["mail_enabled"] is False
        # Đăng ký như chế độ không SMTP: tài khoản xác nhận sẵn, không phát link nào.
        assert client.post("/api/auth/register", json={"email": "moi@example.com", "password": PASSWORD}).status_code == 202
        with client.app.state.session_factory() as db:
            assert db.scalar(select(User).where(User.email == "moi@example.com")).email_verified_at is not None
        for path in ("/api/auth/forgot-password", "/api/auth/resend-verification"):
            response = client.post(path, json={"email": ADMIN_EMAIL})
            assert response.status_code == 409 and response.json() == NO_MAIL, path
        login_admin(client)
        response = client.post("/api/account/email", json={"new_email": "x@example.com", "password": ADMIN_PASSWORD})
        assert response.status_code == 409 and response.json() == NO_MAIL
        assert mailer.sent == []
        # Thư thử không có liên kết: vẫn gửi được để admin kiểm SMTP trước khi đặt APP_BASE_URL.
        response = client.post("/api/system/smtp/test")
        assert response.status_code == 200 and response.json() == {"sent_to": ADMIN_EMAIL}
        assert [(mail.to, mail.subject) for mail in mailer.sent] == [(ADMIN_EMAIL, TEST_SUBJECT)]
        client.cookies.clear()
        assert client.post("/api/auth/login", json={"email": "moi@example.com", "password": PASSWORD}).status_code == 200


def test_env_smtp_without_a_site_address_still_sends_the_test_mail(settings, monkeypatch):
    events = fake_smtp(monkeypatch)
    env = replace(settings, app_base_url=None, smtp_host="smtp.example.com", smtp_from="no-reply@example.com")
    with bare_client(env) as client:
        assert client.get("/api/setup/status").json()["mail_enabled"] is False
        login_admin(client)
        assert client.get("/api/system/settings").json()["smtp"]["source"] == "env"  # nguồn SMTP vẫn nói đúng
        assert client.post("/api/system/smtp/test").status_code == 200
        assert ("send", ADMIN_EMAIL, TEST_SUBJECT, "no-reply@example.com") in events


def test_the_password_changed_notice_has_no_link_without_a_site_address(settings):
    mailer = MemoryMailer()
    with bare_client(settings, mailer, app_base_url=None) as client:
        login_admin(client)
        assert client.post("/api/account/password", json={"current_password": ADMIN_PASSWORD,
                                                           "new_password": "mat-khau-moi-9"}).status_code == 204
        body = mailer.last_to(ADMIN_EMAIL).body
        assert "None" not in body and "://" not in body and "liên hệ quản trị viên" in body


@pytest.mark.parametrize(("env_url", "recorded", "expected"), [
    ("https://app.test", RECORDED, ("https://app.test", "env")),
    (None, RECORDED, (RECORDED, "setup")),
    (None, None, (None, None)),
])
def test_system_settings_show_the_site_address_and_its_source(settings, env_url, recorded, expected):
    with bare_client(settings, app_base_url=env_url) as client:
        record(client, recorded)
        login_admin(client)
        body = client.get("/api/system/settings").json()
        assert (body["site_url"], body["site_url_source"]) == expected
        body = client.put("/api/system/settings", json={"registration_open": True}).json()
        assert (body["site_url"], body["site_url_source"]) == expected
