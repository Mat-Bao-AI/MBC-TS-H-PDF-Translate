import logging
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.errors import ApiError
from app.models import InstanceSettings, User
from app.system.setup import create_admin
from app.system.store import instance_row
from helpers import bare_client

BODY = {"display_name": "  Quản trị  ", "email": "Chu@Example.com", "password": "mat-khau-8"}


def setup(client, **patch):
    return client.post("/api/setup", json={**BODY, **patch})


def status(client):
    return client.get("/api/setup/status").json()


def test_status_on_an_empty_instance(settings):
    with bare_client(settings, seed=False) as client:
        assert status(client) == {"needs_setup": True, "setup_token_required": False, "registration_open": True, "mail_enabled": False}
    with bare_client(settings, seed=False, setup_token="bi-mat", mail_dev_log=True) as client:  # tuần tự, cùng DB trống
        assert status(client) == {"needs_setup": True, "setup_token_required": True, "registration_open": True, "mail_enabled": True}


def test_status_after_setup_is_public_and_says_done(client):
    client.cookies.clear()
    assert status(client)["needs_setup"] is False  # fixture đã chèn admin


def test_setup_creates_a_signed_in_admin(settings):
    with bare_client(settings, seed=False) as client:
        response = setup(client)
        assert response.status_code == 200, response.text
        me = response.json()
        assert (me["email"], me["display_name"], me["is_admin"]) == ("chu@example.com", "Quản trị", True)
        assert any(c.startswith("session=") for c in response.headers.get_list("set-cookie"))
        assert client.get("/api/auth/me").json()["is_admin"] is True
        with client.app.state.session_factory() as db:
            user = db.get(User, me["id"])
            assert user.email_verified_at is not None and user.is_admin
            assert (user.default_engine, user.default_font, user.default_model) == ("google_free", "auto", None)  # default của model
            assert db.get(InstanceSettings, 1).setup_completed_at is not None
        assert status(client)["needs_setup"] is False
        client.cookies.clear()
        assert client.post("/api/auth/login", json={"email": "chu@example.com", "password": "mat-khau-8"}).status_code == 200


def test_a_blank_display_name_is_stored_as_null(settings):
    with bare_client(settings, seed=False) as client:
        assert setup(client, display_name="   ").json()["display_name"] is None


def test_setup_is_refused_once_a_user_exists(client):
    client.cookies.clear()
    response = setup(client)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "setup_done"}}
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_the_conditional_insert_itself_refuses_when_a_user_exists(client):
    # Không qua đường nhanh của router: câu INSERT … WHERE NOT EXISTS là cửa chắn thật (lượt thua cuộc đua tới đây).
    with client.app.state.session_factory() as db:
        with pytest.raises(ApiError) as refused:
            create_admin(db, client.app.state.settings, display_name=None, email_raw="hai@example.com",
                         password="mat-khau-8", setup_token=None)
        assert (refused.value.status, refused.value.code) == (409, "setup_done")
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.get(InstanceSettings, 1).setup_completed_at is None  # không chạm dòng cấu hình khi bị từ chối
        with pytest.raises(ApiError):  # kể cả khi kèm địa chỉ trang: lượt thua không ghi gì
            create_admin(db, client.app.state.settings, display_name=None, email_raw="hai@example.com",
                         password="mat-khau-8", setup_token=None, base_url="https://ke-gian.example/")
        assert db.get(InstanceSettings, 1).site_url is None


@pytest.mark.parametrize(("patch", "code"), [
    ({"email": "khong-phai-email"}, "invalid_email"), ({"password": "ngan"}, "invalid_password"),
    ({"display_name": "x" * 51}, "invalid_display_name"), ({"display_name": "a\u200bb"}, "invalid_display_name"),
])
def test_setup_validates_input(settings, patch, code):
    with bare_client(settings, seed=False) as client:
        response = setup(client, **patch)
        assert response.status_code == 422 and response.json() == {"detail": {"code": code}}
        assert status(client)["needs_setup"] is True


def test_setup_token_is_required_when_configured(settings):
    with bare_client(settings, seed=False, setup_token="bi-mat-cai-dat") as client:
        for body in ({}, {"setup_token": ""}, {"setup_token": "sai"}, {"setup_token": "sai", "email": "khong-hop-le"}):
            response = setup(client, **body)
            assert response.status_code == 403 and response.json() == {"detail": {"code": "invalid_setup_token"}}, body
        assert status(client)["needs_setup"] is True
        assert setup(client, setup_token="bi-mat-cai-dat").status_code == 200


def test_a_lone_surrogate_setup_token_is_refused_not_a_server_error(settings):
    raw = '{"email": "chu@example.com", "password": "mat-khau-8", "setup_token": "\\ud800"}'  # JSON hợp lệ, không mã hoá UTF-8 được
    with bare_client(settings, seed=False, setup_token="bi-mat") as client:
        response = client.post("/api/setup", content=raw, headers={"Content-Type": "application/json"})
        assert response.status_code == 403 and response.json() == {"detail": {"code": "invalid_setup_token"}}
        assert status(client)["needs_setup"] is True


def test_setup_shares_the_ip_throttle_with_the_other_public_forms(settings):
    # MAIL_DEV_LOG: quên mật khẩu / gửi lại thư qua được require_mail trên instance trống → tiêu đúng hạn mức IP chung
    # (đăng ký thì không: setup_required chặn trước throttle).
    with bare_client(settings, seed=False, setup_token="bi-mat", mail_dev_log=True) as client:
        for _ in range(4):
            assert client.post("/api/auth/forgot-password", json={"email": "ai@example.com"}).status_code == 202
        for _ in range(3):
            assert client.post("/api/auth/resend-verification", json={"email": "ai@example.com"}).status_code == 202
        for _ in range(3):
            assert setup(client, setup_token="sai").status_code == 403
        response = setup(client, setup_token="bi-mat")  # mã đúng vẫn bị chặn: 10 lượt chung của IP đã hết
        assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_requests"}}
        assert client.post("/api/auth/forgot-password", json={"email": "ai@example.com"}).status_code == 429
        assert status(client)["needs_setup"] is True


def test_two_simultaneous_setups_yield_exactly_one_admin(settings):
    with bare_client(settings, seed=False) as client:
        barrier = threading.Barrier(2)
        results: list[int] = []

        def go(email: str) -> None:
            # TestClient KHÔNG dùng `with`: không chạy lại lifespan (sẽ stop runner / dispose engine của client ngoài).
            other = TestClient(client.app, base_url="https://testserver", headers={"X-Requested-With": "fetch"})
            barrier.wait()
            results.append(other.post("/api/setup", json={**BODY, "email": email}).status_code)

        threads = [threading.Thread(target=go, args=(email,)) for email in ("mot@example.com", "hai@example.com")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == [200, 409]
        with client.app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(User)) == 1
            assert db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) == 1


def test_register_and_login_are_refused_until_setup(settings):
    with bare_client(settings, seed=False) as client:
        for _ in range(12):  # trước throttle, trước validate: không tốn hạn mức, không băm
            response = client.post("/api/auth/register", json={"email": "ai@example.com", "password": "mat-khau-8"})
            assert response.status_code == 409 and response.json() == {"detail": {"code": "setup_required"}}
        response = client.post("/api/auth/login", json={"email": "ai@example.com", "password": "mat-khau-8"})
        assert response.status_code == 409 and response.json() == {"detail": {"code": "setup_required"}}
        assert setup(client).status_code == 200  # throttle còn nguyên 10 lượt cho /api/setup
        client.cookies.clear()
        assert client.post("/api/auth/register", json={"email": "ai@example.com", "password": "mat-khau-8"}).status_code == 202


def test_setup_required_comes_before_a_closed_registration(settings):
    with bare_client(settings, seed=False) as client:
        with client.app.state.session_factory() as db:
            instance_row(db).registration_open = False
            db.commit()
        response = client.post("/api/auth/register", json={"email": "ai@example.com", "password": "mat-khau-8"})
        assert response.status_code == 409 and response.json() == {"detail": {"code": "setup_required"}}


def test_setup_is_public_but_needs_the_fetch_header(settings):
    with bare_client(settings, seed=False) as client:
        forged = client.post("/api/setup", json=BODY, headers={"X-Requested-With": ""})
        assert forged.status_code == 403 and forged.json() == {"detail": {"code": "csrf"}}
        assert client.get("/api/setup/status", headers={"X-Requested-With": ""}).status_code == 200


def recorded_site_url(client) -> str | None:
    with client.app.state.session_factory() as db:
        return db.get(InstanceSettings, 1).site_url


@pytest.mark.parametrize(("base_url", "recorded"), [
    ("https://pdf.example", "https://pdf.example"),
    ("https://pdf.example:8443", "https://pdf.example:8443"),
    ("http://localhost:8000", "http://localhost:8000"),
    ("http://127.0.0.1:18081", "http://127.0.0.1:18081"),
])
def test_setup_records_the_address_it_was_completed_on(settings, base_url, recorded):
    with bare_client(settings, seed=False, base_url=base_url) as client:
        assert recorded_site_url(client) is None
        assert setup(client).status_code == 200
        assert recorded_site_url(client) == recorded


def test_setup_over_plain_http_records_nothing_and_still_succeeds(settings, caplog):
    with caplog.at_level(logging.WARNING), bare_client(settings, seed=False, base_url="http://testserver") as client:
        response = setup(client)
        assert response.status_code == 200, response.text
        assert response.json()["is_admin"] is True
        assert recorded_site_url(client) is None
        assert status(client)["needs_setup"] is False
    warnings = [record for record in caplog.records if "http://testserver" in record.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert "mat-khau-8" not in caplog.text


def test_setup_takes_the_scheme_from_the_proxy(settings):
    # Dockerfile chạy uvicorn --proxy-headers: Traefik kết thúc TLS, gọi vào bằng http + X-Forwarded-Proto: https.
    with bare_client(settings, seed=False) as inner:
        proxied = TestClient(ProxyHeadersMiddleware(inner.app, trusted_hosts="*"), base_url="http://pdf.example",
                             headers={"X-Requested-With": "fetch", "X-Forwarded-Proto": "https"})
        assert proxied.post("/api/setup", json=BODY).status_code == 200
        assert recorded_site_url(inner) == "https://pdf.example"


def test_a_refused_second_setup_never_overwrites_the_recorded_address(settings):
    with bare_client(settings, seed=False, base_url="https://pdf.example") as client:
        assert setup(client).status_code == 200
    with bare_client(settings, seed=False, base_url="https://ke-gian.example") as client:  # cùng DB, đã có admin
        response = setup(client, email="hai@example.com")
        assert response.status_code == 409 and response.json() == {"detail": {"code": "setup_done"}}
        assert recorded_site_url(client) == "https://pdf.example"


def test_a_second_setup_after_every_account_is_gone_keeps_the_first_address(settings):
    # Admin duy nhất tự xoá tài khoản → instance trống, /setup mở lại: địa chỉ đã ghi không đổi (chỉ ghi khi còn NULL).
    with bare_client(settings, seed=False, base_url="https://pdf.example") as client:
        assert setup(client).status_code == 200
        with client.app.state.session_factory() as db:
            db.execute(delete(User))
            db.commit()
    with bare_client(settings, seed=False, base_url="https://khac.example") as client:
        assert setup(client, email="hai@example.com").status_code == 200
        assert recorded_site_url(client) == "https://pdf.example"


@pytest.mark.parametrize("base_url", [
    "https://pdf.example/con/", "https://pdf.example/?x=1", "https://ai@pdf.example/", "https://pdf.example:cong/",
    "http://[::1/", "https:///", "https://pdf.example#", "https://pdf.example?", "https://pdf.example;x",
    "https://pdf.example%2F", "https://pdf.example\\",
])
def test_only_a_bare_origin_is_recorded(settings, base_url, caplog):
    # Host lạ (proxy không chuẩn, Host tự đặt): không ghi gì ngoài gốc scheme://máy[:cổng] — admin vẫn tạo được.
    with caplog.at_level(logging.WARNING), bare_client(settings, seed=False) as client:
        with client.app.state.session_factory() as db:
            user = create_admin(db, client.app.state.settings, display_name=None, email_raw="chu@example.com",
                                password="mat-khau-8", setup_token=None, base_url=base_url)
            assert user.is_admin and db.get(InstanceSettings, 1).site_url is None
    # Chỉ đếm đúng câu cảnh báo "không ghi địa chỉ trang" — không phụ thuộc log khác trên logger system.
    assert len([r for r in caplog.records if r.levelno == logging.WARNING and "không ghi địa chỉ trang" in r.getMessage()]) == 1


def test_recording_logs_one_info_line_with_the_address(settings, caplog):
    # Ops cần thấy địa chỉ đã ghi để phát hiện giá trị sai (không có bí mật nào trong đó).
    with caplog.at_level(logging.INFO, logger="system"), bare_client(settings, seed=False, base_url="https://pdf.example") as client:
        assert setup(client).status_code == 200
    lines = [r for r in caplog.records if r.levelno == logging.INFO and "https://pdf.example" in r.getMessage()]
    assert len(lines) == 1


def test_no_host_header_records_nothing(settings, caplog):
    # Không có Host: Starlette quay về scope["server"] (IP nội bộ sau proxy) — không được ghi địa chỉ đó.
    with caplog.at_level(logging.INFO, logger="system"), bare_client(settings, seed=False, base_url="https://pdf.example") as client:
        assert client.post("/api/setup", json=BODY, headers={"host": ""}).status_code == 200
        assert recorded_site_url(client) is None
    assert any(r.levelno == logging.WARNING and "không ghi địa chỉ trang" in r.getMessage() for r in caplog.records)
