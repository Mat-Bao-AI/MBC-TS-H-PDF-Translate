import logging
import smtplib
from dataclasses import replace

import pytest
from sqlalchemy import update

from app.models import User
from app.system.store import instance_row, seal_smtp_password
from helpers import bare_client, fake_smtp, login_admin

SMTP = {"host": "smtp.example.com", "port": 587, "security": "starttls", "username": "u", "password": "mat-khau-smtp",
        "from": "PDF <no-reply@example.com>"}


@pytest.fixture
def admin(client, sign_up) -> dict:
    me = sign_up("quan-tri@example.com")
    with client.app.state.session_factory() as db:
        db.execute(update(User).where(User.id == me["id"]).values(is_admin=True))
        db.commit()
    return me


def get(client):
    return client.get("/api/system/settings")


def put(client, **body):
    return client.put("/api/system/settings", json=body)


def send_test(client, smtp=None):
    return client.post("/api/system/smtp/test", json=None if smtp is None else {"smtp": smtp})


def test_system_routes_need_a_session_and_an_admin(client, sign_up):
    calls = [("GET", "/api/system/settings", None), ("PUT", "/api/system/settings", {}),
             ("DELETE", "/api/system/settings/smtp", None), ("POST", "/api/system/smtp/test", None)]
    for method, path, body in calls:
        assert client.request(method, path, json=body).status_code == 401, path
    sign_up("thuong@example.com")
    for method, path, body in calls:
        response = client.request(method, path, json=body)
        assert response.status_code == 403 and response.json() == {"detail": {"code": "admin_required"}}, path


def test_get_with_an_injected_mailer_counts_as_dev_log_and_never_has_a_password(client, admin):
    body = get(client).json()
    assert body["smtp"] == {"source": "dev_log", "host": "", "port": 587, "security": "starttls", "username": "", "from": "",
                            "password_status": "none"}
    assert (body["registration_open"], body["max_pending_per_user"], body["max_pending_default"]) == (True, None, 3)


def test_get_with_nothing_configured_says_none(settings):
    with bare_client(settings) as client:
        login_admin(client)
        assert get(client).json()["smtp"]["source"] == "none"


def test_get_with_env_smtp_prefills_the_form(settings):
    env = replace(settings, smtp_host="env.example.com", smtp_port=465, smtp_security="ssl", smtp_user="envu",
                  smtp_password="envpw", smtp_from="env@example.com")
    with bare_client(env) as client:
        login_admin(client)
        assert get(client).json()["smtp"] == {"source": "env", "host": "env.example.com", "port": 465, "security": "ssl",
                                              "username": "envu", "from": "env@example.com", "password_status": "saved"}


def test_put_smtp_saves_and_switches_the_source_to_settings(client, admin):
    response = put(client, smtp=SMTP)
    assert response.status_code == 200
    assert response.json()["smtp"] == {"source": "settings", "host": "smtp.example.com", "port": 587, "security": "starttls",
                                       "username": "u", "from": "PDF <no-reply@example.com>", "password_status": "saved"}
    assert "mat-khau-smtp" not in response.text and "mat-khau-smtp" not in get(client).text


def test_put_with_an_empty_password_keeps_the_saved_one(client, admin, monkeypatch):
    put(client, smtp=SMTP)
    assert put(client, smtp={**SMTP, "password": "", "port": 2525}).json()["smtp"]["password_status"] == "saved"
    assert put(client, smtp={k: v for k, v in SMTP.items() if k != "password"}).status_code == 200
    events = fake_smtp(monkeypatch)
    assert send_test(client, {**SMTP, "password": ""}).status_code == 200  # ô trống trong form thử = mật khẩu đã lưu
    assert ("login", "u", "mat-khau-smtp") in events


def test_put_username_without_any_password_is_refused(client, admin):
    response = put(client, smtp={**SMTP, "password": ""})
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_smtp", "field": "password"}}
    assert get(client).json()["smtp"]["source"] == "dev_log"  # không ghi gì
    assert put(client, smtp={**SMTP, "username": "", "password": ""}).status_code == 200  # không đăng nhập SMTP: không cần mật khẩu


@pytest.mark.parametrize(("patch", "field"), [
    ({"host": "smtp example.com"}, "host"), ({"host": ""}, "host"), ({"host": "a" * 254}, "host"),
    ({"port": 0}, "port"), ({"port": 65536}, "port"), ({"security": "tls"}, "security"),
    ({"username": "u" * 255}, "username"), ({"from": "khong-phai-email"}, "from"), ({"from": ""}, "from"),
    ({"from": "P\x07DF <no-reply@example.com>"}, "from"),
])
def test_put_validates_each_smtp_field(client, admin, patch, field):
    response = put(client, smtp={**SMTP, **patch})
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_smtp", "field": field}}
    assert get(client).json()["smtp"]["source"] == "dev_log"


def test_put_registration_and_limit_and_fields_left_out_are_kept(client, admin):
    body = put(client, registration_open=False, max_pending_per_user=7).json()
    assert (body["registration_open"], body["max_pending_per_user"]) == (False, 7)
    body = put(client, smtp=SMTP).json()  # không nhắc tới → giữ nguyên
    assert (body["registration_open"], body["max_pending_per_user"]) == (False, 7)
    assert put(client, max_pending_per_user=None).json()["max_pending_per_user"] is None  # null = về env
    assert put(client, registration_open=True).json()["registration_open"] is True


@pytest.mark.parametrize("limit", [0, 101, -1, True, "5", 2.5])
def test_limit_out_of_range_is_refused(client, admin, limit):
    response = put(client, max_pending_per_user=limit, registration_open=False)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_limit"}}
    assert get(client).json()["registration_open"] is True  # cả thẻ không ghi gì


def test_delete_smtp_returns_to_env_or_none(settings):
    env = replace(settings, smtp_host="env.example.com", smtp_from="env@example.com")
    with bare_client(env) as client:
        login_admin(client)
        assert put(client, smtp=SMTP).json()["smtp"]["source"] == "settings"
        assert client.delete("/api/system/settings/smtp").status_code == 204
        assert get(client).json()["smtp"] == {"source": "env", "host": "env.example.com", "port": 587, "security": "starttls",
                                              "username": "", "from": "env@example.com", "password_status": "none"}
        with client.app.state.session_factory() as db:
            row = instance_row(db)
            assert (row.smtp_host, row.smtp_port, row.smtp_security, row.smtp_username, row.smtp_password_enc, row.smtp_from) == (
                None,) * 6


def test_a_rotated_secret_makes_the_saved_password_unreadable(client, admin):
    put(client, smtp=SMTP)
    with client.app.state.session_factory() as db:
        instance_row(db).smtp_password_enc = seal_smtp_password("x" * 32, "mat-khau-smtp")  # mã hoá bằng SECRET_KEY khác
        db.commit()
    assert get(client).json()["smtp"]["password_status"] == "unreadable"
    response = put(client, smtp={**SMTP, "password": ""})  # có username mà mật khẩu không đọc được: phải nhập lại
    assert response.status_code == 422 and response.json()["detail"]["field"] == "password"
    assert put(client, smtp=SMTP).json()["smtp"]["password_status"] == "saved"


def test_smtp_test_sends_with_the_form_values_to_the_admin(client, admin, monkeypatch):
    events = fake_smtp(monkeypatch)
    response = send_test(client, {**SMTP, "host": "thu.example.com", "security": "ssl", "port": 465})
    assert response.status_code == 200 and response.json() == {"sent_to": "quan-tri@example.com"}
    assert events[0] == ("SMTP_SSL", "thu.example.com", 465, 15)
    assert ("login", "u", "mat-khau-smtp") in events
    assert ("send", "quan-tri@example.com", "Thư thử từ PDF Translate", "PDF <no-reply@example.com>") in events
    assert get(client).json()["smtp"]["source"] == "dev_log"  # thử không lưu


def test_smtp_test_failure_reports_the_class_and_masks_the_password(client, admin, monkeypatch, caplog):
    events = fake_smtp(monkeypatch)
    events.raise_on_login = smtplib.SMTPAuthenticationError(535, b"5.7.8 bad password mat-khau-smtp " + b"x" * 300)
    with caplog.at_level(logging.WARNING, logger="system"):
        response = send_test(client, SMTP)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "smtp_failed" and detail["reason"].startswith("SMTPAuthenticationError:")
    assert "mat-khau-smtp" not in detail["reason"] and "***" in detail["reason"] and len(detail["reason"]) <= 200
    [record] = [record for record in caplog.records if record.name == "system"]
    assert "SMTPAuthenticationError" in record.getMessage()
    assert "mat-khau-smtp" not in caplog.text and "smtp.example.com" not in record.getMessage()  # log: không mật khẩu, không host


def test_smtp_test_is_limited_to_six_per_minute_per_admin(client, admin, monkeypatch):
    fake_smtp(monkeypatch)
    client.app.state.auth.mail_throttle.reset("quan-tri@example.com")  # thư xác thực lúc sign_up đã tính vào đây
    for _ in range(6):
        assert send_test(client, SMTP).status_code == 200
    response = send_test(client, SMTP)
    assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_requests"}}
    assert client.app.state.auth.mail_throttle.blocked("quan-tri@example.com") is False  # không đi qua mail_throttle 60 s


def test_smtp_test_without_body_or_config_is_409(settings):
    with bare_client(settings) as client:
        login_admin(client)
        response = send_test(client)
        assert response.status_code == 409 and response.json() == {"detail": {"code": "mail_not_configured"}}


def test_smtp_test_without_body_uses_the_effective_mailer(client, admin, mailer):
    assert send_test(client).json() == {"sent_to": "quan-tri@example.com"}  # mailer tiêm = cấu hình hiệu lực
    assert mailer.last_to("quan-tri@example.com").subject == "Thư thử từ PDF Translate"


def test_smtp_test_without_body_masks_the_saved_password_too(settings, monkeypatch):
    with bare_client(settings) as client:
        login_admin(client)
        put(client, smtp={**SMTP, "password": "mật-khẩu-smtp"})
        events = fake_smtp(monkeypatch)
        events.raise_on_login = smtplib.SMTPAuthenticationError(535, "5.7.8 bad mật-khẩu-smtp".encode())
        response = send_test(client)  # không body: dùng cấu hình đã lưu trong DB
        assert ("login", "u", "mật-khẩu-smtp") in events
        reason = response.json()["detail"]["reason"]
        assert response.status_code == 502 and "***" in reason, reason
        assert "mật-khẩu-smtp" not in reason and "m\\xe1\\xba\\xadt" not in reason  # cả dạng bytes của thông điệp SMTP


def test_an_empty_password_on_the_env_prefilled_form_keeps_the_env_password(settings, monkeypatch):
    env = replace(settings, smtp_host="env.example.com", smtp_user="envu", smtp_password="env-mat-khau",
                  smtp_from="env@example.com")
    with bare_client(env) as client:
        login_admin(client)
        assert get(client).json()["smtp"]["password_status"] == "saved"  # form báo "Đã lưu — để trống nếu giữ nguyên"
        form = {"host": "env.example.com", "port": 587, "security": "starttls", "username": "envu", "password": "",
                "from": "env@example.com"}
        events = fake_smtp(monkeypatch)
        assert send_test(client, form).status_code == 200
        assert ("login", "envu", "env-mat-khau") in events
        body = put(client, smtp=form).json()["smtp"]
        assert (body["source"], body["password_status"]) == ("settings", "saved")  # mật khẩu env chép (mã hoá) vào DB
        events.clear()
        assert send_test(client).status_code == 200  # cấu hình DB vừa lưu đăng nhập bằng đúng mật khẩu đó
        assert ("login", "envu", "env-mat-khau") in events


ENV = {"smtp_host": "env.example.com", "smtp_user": "envu", "smtp_password": "env-mat-khau", "smtp_from": "env@example.com"}
ENV_FORM = {"host": "env.example.com", "port": 587, "security": "starttls", "username": "envu", "password": "",
            "from": "env@example.com"}
INVALID_PASSWORD = {"detail": {"code": "invalid_smtp", "field": "password"}}


@pytest.mark.parametrize("change", [{"host": "attacker.example"}, {"security": "none"}, {"security": "ssl", "port": 465}])
def test_the_env_password_is_only_reused_for_the_env_host_and_security(settings, monkeypatch, change):
    with bare_client(replace(settings, **ENV)) as client:
        login_admin(client)
        form = {**ENV_FORM, **change}
        events = fake_smtp(monkeypatch)
        for response in (send_test(client, form), put(client, smtp=form)):
            assert response.status_code == 422 and response.json() == INVALID_PASSWORD
        assert events == []  # không mở kết nối nào: mật khẩu env không bao giờ tới host / kênh khác
        assert get(client).json()["smtp"]["source"] == "env"  # PUT không ghi gì


@pytest.mark.parametrize("change", [{"host": "attacker.example"}, {"security": "none"}, {"security": "ssl", "port": 465}])
def test_the_saved_password_is_only_reused_for_the_saved_host_and_security(client, admin, monkeypatch, change):
    put(client, smtp=SMTP)
    form = {**SMTP, **change, "password": ""}
    events = fake_smtp(monkeypatch)
    for response in (send_test(client, form), put(client, smtp=form)):
        assert response.status_code == 422 and response.json() == INVALID_PASSWORD
    assert events == []
    smtp = get(client).json()["smtp"]
    assert (smtp["host"], smtp["security"], smtp["password_status"]) == ("smtp.example.com", "starttls", "saved")


def test_the_saved_host_matches_without_case_or_surrounding_spaces(client, admin, monkeypatch):
    put(client, smtp=SMTP)
    events = fake_smtp(monkeypatch)
    assert send_test(client, {**SMTP, "host": " SMTP.Example.COM ", "password": ""}).status_code == 200
    assert ("login", "u", "mat-khau-smtp") in events


@pytest.mark.parametrize("change", [{"host": "attacker.example"}, {"security": "none"}])
def test_moving_the_saved_config_elsewhere_drops_the_saved_password(client, admin, monkeypatch, change):
    put(client, smtp=SMTP)
    body = put(client, smtp={**SMTP, **change, "username": "", "password": ""}).json()["smtp"]
    assert body["password_status"] == "none"  # mật khẩu của smtp.example.com/starttls không đi theo sang nơi khác
    events = fake_smtp(monkeypatch)
    response = send_test(client, {**SMTP, **change, "password": ""})  # rồi bật lại username với ô trống
    assert response.status_code == 422 and response.json() == INVALID_PASSWORD and events == []


def test_an_env_password_without_an_env_host_is_not_reported_as_saved(settings):
    with bare_client(replace(settings, smtp_password="env-mat-khau")) as client:
        login_admin(client)
        assert get(client).json()["smtp"]["password_status"] == "none"  # ô trống không dùng được nó → không báo "saved"


@pytest.mark.parametrize("port", [True, "587", 587.5, None])
def test_a_port_that_is_not_an_integer_is_an_smtp_field_error(client, admin, monkeypatch, port):
    events = fake_smtp(monkeypatch)
    for response in (put(client, smtp={**SMTP, "port": port}), send_test(client, {**SMTP, "port": port})):
        assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_smtp", "field": "port"}}
    assert events == []


@pytest.mark.parametrize(("patch", "field"), [({"port": 0}, "port"), ({"password": ""}, "password")])
def test_an_invalid_smtp_block_leaves_the_whole_put_unwritten(client, admin, patch, field):
    response = put(client, smtp={**SMTP, **patch}, registration_open=False, max_pending_per_user=7)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_smtp", "field": field}}
    body = get(client).json()
    assert (body["smtp"]["source"], body["registration_open"], body["max_pending_per_user"]) == ("dev_log", True, None)


@pytest.mark.parametrize(("security", "expected"), [("ssl", ("ssl", 465)), ("none", ("none", 587)), (None, ("starttls", 587))])
def test_a_db_row_without_port_or_security_reads_back_as_the_defaults(client, admin, security, expected):
    put(client, smtp=SMTP)
    with client.app.state.session_factory() as db:
        row = instance_row(db)
        row.smtp_security, row.smtp_port = security, None  # cột rỗng (sửa tay / dữ liệu cũ)
        db.commit()
    smtp = get(client).json()["smtp"]
    assert (smtp["security"], smtp["port"]) == expected
