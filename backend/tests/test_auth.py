import threading
import time
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.auth import service as auth_service
from app.db import utcnow
from app.errors import ApiError
from app.models import EmailToken, User, UserSession
from app.system.store import instance_row
from helpers import bare_client, token_in

PASSWORD = "mat-khau-8"


def register(client, email, password=PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def me_with(client, token):
    client.cookies.clear()
    return client.get("/api/auth/me", headers={"Cookie": f"session={token}"})


def db_of(client):
    return client.app.state.session_factory()


def unthrottle(client, email):
    client.app.state.auth.mail_throttle.reset(email)


def nonce_cookie_shape(response):
    """Cookie verify_nonce của một phản hồi 202, bỏ giá trị: (độ dài giá trị, các thuộc tính)."""
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 1 and cookies[0].startswith("verify_nonce="), cookies
    value, *attributes = cookies[0].split("; ")
    return len(value), tuple(sorted(part.lower() for part in attributes))


def test_register_sends_verification_link(client, mailer):
    response = register(client, "an@example.com")
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert "https://app.test/verify-email?token=" in mailer.last_to("an@example.com").body


def test_register_existing_account_looks_the_same_and_warns_owner(client, mailer, sign_up):
    sign_up("an@example.com")
    unthrottle(client, "an@example.com")
    response = register(client, "an@example.com", "mat-khau-khac")
    assert response.status_code == 202 and response.json() == {"status": "accepted"}
    mail = mailer.last_to("an@example.com")
    assert "đã có tài khoản" in mail.body and "token=" not in mail.body
    client.cookies.clear()
    assert login(client, "an@example.com").status_code == 200  # mật khẩu cũ không bị đổi


def test_register_mail_is_throttled_per_email(client, mailer):
    register(client, "an@example.com")
    register(client, "an@example.com")
    assert len([m for m in mailer.sent if m.to == "an@example.com"]) == 1


def test_register_again_while_unverified_sends_existing_account_mail_and_kills_pending_links(client, mailer):
    register(client, "an@example.com")
    first = token_in(mailer.last_to("an@example.com"))
    unthrottle(client, "an@example.com")
    again = register(client, "an@example.com")
    assert again.status_code == 202 and again.json() == {"status": "accepted"}
    # Không phát token mới nhưng vẫn có cookie cùng dạng (nonce mồi, không khớp token nào): cookie không lộ email đã có.
    assert nonce_cookie_shape(again) == nonce_cookie_shape(register(client, "moi@example.com"))
    mail = mailer.last_to("an@example.com")
    assert "đã có tài khoản" in mail.body and "token=" not in mail.body
    dead = client.post("/api/auth/verify-email", json={"token": first})
    assert dead.status_code == 400 and dead.json() == {"detail": {"code": "invalid_token"}}


def test_register_sets_a_locked_down_verify_nonce_cookie(client):
    response = register(client, "an@example.com")
    assert response.json() == {"status": "accepted"}
    cookie = response.headers["set-cookie"].lower()
    for part in ("verify_nonce=", "httponly", "secure", "samesite=lax", "path=/api/auth", "max-age=86400"):
        assert part in cookie


def test_register_looks_identical_for_free_and_taken_addresses(client, sign_up):
    sign_up("roi@example.com")  # đã có tài khoản, đã xác thực
    client.cookies.clear()
    register(client, "chua@example.com")  # đã có tài khoản, chưa xác thực
    for email in ("roi@example.com", "chua@example.com"):
        unthrottle(client, email)
    client.cookies.clear()
    shapes = set()
    for email in ("moi@example.com", "roi@example.com", "chua@example.com"):
        response = register(client, email)
        shapes.add((response.status_code, response.content, nonce_cookie_shape(response)))
    assert len(shapes) == 1, shapes


def test_verify_in_the_same_browser_signs_in_and_clears_the_nonce(client, mailer):
    register(client, "an@example.com")
    response = client.post("/api/auth/verify-email", json={"token": token_in(mailer.last_to("an@example.com"))})
    assert response.status_code == 200 and set(response.json()) == {"id", "email", "display_name", "is_admin", "smtp_notice_dismissed", "advance_mode"}
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("session=") for c in cookies)
    cleared = [c.lower() for c in cookies if c.startswith("verify_nonce=")]
    assert cleared and "max-age=0" in cleared[0] and "path=/api/auth" in cleared[0]
    assert client.get("/api/auth/me").status_code == 200


def test_verify_from_another_browser_verifies_without_signing_in(client, mailer):
    register(client, "an@example.com")
    token = token_in(mailer.last_to("an@example.com"))
    client.cookies.clear()  # mở link ở trình duyệt khác
    response = client.post("/api/auth/verify-email", json={"token": token})
    assert response.status_code == 200 and response.json() == {"status": "verified"}
    assert "session=" not in response.headers.get("set-cookie", "")
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, "an@example.com").status_code == 200  # email đã xác nhận thật


def test_attackers_verify_link_cannot_sign_the_victim_in(client, mailer):
    with from_ip(client, "10.6.6.6") as attacker:
        register(attacker, "nan-nhan@example.com", "mat-khau-ke-gian")
    link = token_in(mailer.last_to("nan-nhan@example.com"))
    client.cookies.clear()
    response = client.post("/api/auth/verify-email", json={"token": link})  # nạn nhân bấm link trong thư
    assert response.json() == {"status": "verified"}
    assert client.get("/api/auth/me").status_code == 401


def test_victim_reregistering_kills_the_attackers_pending_link(client, mailer):
    with from_ip(client, "10.6.6.6") as attacker:
        register(attacker, "nan-nhan@example.com", "mat-khau-ke-gian")
        link = token_in(mailer.last_to("nan-nhan@example.com"))
        unthrottle(client, "nan-nhan@example.com")
        client.cookies.clear()
        victim = register(client, "nan-nhan@example.com", "mat-khau-that")
        assert victim.status_code == 202 and victim.json() == {"status": "accepted"}
        assert "đã có tài khoản" in mailer.last_to("nan-nhan@example.com").body
        for who in (client, attacker):
            dead = who.post("/api/auth/verify-email", json={"token": link})
            assert dead.status_code == 400 and dead.json() == {"detail": {"code": "invalid_token"}}
        assert login(attacker, "nan-nhan@example.com", "mat-khau-ke-gian").json() == {
            "detail": {"code": "email_unverified"}}


def test_resend_binds_the_new_link_to_the_browser_that_asked(client, mailer):
    register(client, "an@example.com")
    unthrottle(client, "an@example.com")
    with from_ip(client, "10.0.0.2") as phone:
        resent = phone.post("/api/auth/resend-verification", json={"email": "an@example.com"})
        assert resent.json() == {"status": "accepted"} and "verify_nonce=" in resent.headers["set-cookie"]
        token = token_in(mailer.last_to("an@example.com"))
        assert phone.post("/api/auth/verify-email", json={"token": token}).json()["email"] == "an@example.com"
        assert phone.get("/api/auth/me").status_code == 200


def test_resend_looks_identical_whether_or_not_a_link_was_sent(client, sign_up):
    sign_up("roi@example.com")
    client.cookies.clear()
    register(client, "chua@example.com")
    for email in ("roi@example.com", "chua@example.com"):
        unthrottle(client, email)
    client.cookies.clear()
    shapes = set()
    for email in ("chua@example.com", "roi@example.com", "khong-co@example.com"):  # chỉ địa chỉ đầu nhận link
        response = client.post("/api/auth/resend-verification", json={"email": email})
        shapes.add((response.status_code, response.content, nonce_cookie_shape(response)))
    assert len(shapes) == 1, shapes


def test_simultaneous_registration_of_a_new_email_is_not_a_500(client, mailer, monkeypatch):
    register(client, "an@example.com")
    unthrottle(client, "an@example.com")
    auth = client.app.state.auth
    real = auth._user_by_email
    calls = []

    def racing(db, email):
        calls.append(email)
        return None if len(calls) == 1 else real(db, email)  # lần đầu "chưa thấy" — bản kia chưa commit

    monkeypatch.setattr(auth, "_user_by_email", racing)
    response = register(client, "an@example.com", "mat-khau-khac")
    assert response.status_code == 202 and response.json() == {"status": "accepted"}
    assert "đã có tài khoản" in mailer.last_to("an@example.com").body
    with db_of(client) as db:
        assert len(db.scalars(select(auth_service.User).where(User.email == "an@example.com")).all()) == 1


def test_pre_registered_account_cannot_be_hijacked(client, mailer):
    register(client, "an@example.com", "mat-khau-ke-gian")
    attacker_token = token_in(mailer.last_to("an@example.com"))
    unthrottle(client, "an@example.com")
    register(client, "an@example.com", "mat-khau-that")
    mail = mailer.last_to("an@example.com")
    assert "đã có tài khoản" in mail.body and "token=" not in mail.body
    unthrottle(client, "an@example.com")
    assert client.post("/api/auth/forgot-password", json={"email": "an@example.com"}).status_code == 202
    reset_token = token_in(mailer.last_to("an@example.com"))
    reset = client.post("/api/auth/reset-password", json={"token": reset_token, "password": "mat-khau-that"})
    assert reset.status_code == 204
    assert login(client, "an@example.com", "mat-khau-ke-gian").status_code == 401
    assert login(client, "an@example.com", "mat-khau-that").status_code == 200
    again = client.post("/api/auth/verify-email", json={"token": attacker_token})
    assert again.status_code == 400 and again.json() == {"detail": {"code": "invalid_token"}}


@pytest.mark.parametrize(("email", "password", "code"), [
    ("khong-phai-email", PASSWORD, "invalid_email"),
    ("an@example.com", "ngan", "invalid_password"),
    ("an@example.com", "x" * 129, "invalid_password"),
])
def test_register_validates_input(client, email, password, code):
    response = register(client, email, password)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": code}}


def test_email_is_normalized(client, mailer):
    register(client, "  An@Example.COM ")
    token = token_in(mailer.last_to("an@example.com"))
    assert client.post("/api/auth/verify-email", json={"token": token}).json()["email"] == "an@example.com"
    client.cookies.clear()
    assert login(client, "AN@example.com").status_code == 200


def test_verify_email_signs_in_once(client, mailer):
    register(client, "an@example.com")
    token = token_in(mailer.last_to("an@example.com"))
    response = client.post("/api/auth/verify-email", json={"token": token})
    assert response.status_code == 200 and response.json()["email"] == "an@example.com"
    assert client.get("/api/auth/me").json()["email"] == "an@example.com"
    again = client.post("/api/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and again.json() == {"detail": {"code": "invalid_token"}}


def test_expired_verification_link_is_rejected(client, mailer):
    register(client, "an@example.com")
    token = token_in(mailer.last_to("an@example.com"))
    with db_of(client) as db:
        db.execute(update(EmailToken).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400


def test_session_cookie_is_locked_down(client, mailer):
    register(client, "an@example.com")
    response = client.post("/api/auth/verify-email", json={"token": token_in(mailer.last_to("an@example.com"))})
    cookie = response.headers["set-cookie"].lower()
    for part in ("session=", "httponly", "secure", "samesite=lax", "max-age=604800", "path=/"):
        assert part in cookie


def test_unverified_login_is_refused_only_with_the_right_password(client):
    register(client, "an@example.com")
    assert login(client, "an@example.com").json() == {"detail": {"code": "email_unverified"}}
    wrong = login(client, "an@example.com", "sai-mat-khau")
    assert wrong.status_code == 401 and wrong.json() == {"detail": {"code": "invalid_credentials"}}


def test_wrong_password_and_unknown_email_look_the_same(client, sign_up):
    sign_up("an@example.com")
    client.cookies.clear()
    wrong = login(client, "an@example.com", "sai-mat-khau")
    unknown = login(client, "ai-do@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_locks_after_five_failures(client, sign_up):
    sign_up("an@example.com")
    client.cookies.clear()
    for _ in range(5):
        assert login(client, "an@example.com", "sai-mat-khau").status_code == 401
    locked = login(client, "an@example.com")
    assert locked.status_code == 429 and locked.json() == {"detail": {"code": "too_many_attempts"}}


RAW_JSON = {"Content-Type": "application/json", "X-Requested-With": "fetch"}  # thân JSON gõ tay (surrogate lẻ…)


def test_an_email_that_is_not_valid_unicode_is_just_an_unknown_account(client):
    """`\\ud800` hợp lệ trong JSON nhưng không mã hoá được UTF-8: trả lời như email không có tài khoản, vẫn bị đếm."""
    unknown = login(client, "ai-do@example.com")
    body = '{"email": "a\\ud800@example.com", "password": "mat-khau-8"}'
    for _ in range(5):
        response = client.post("/api/auth/login", content=body, headers=RAW_JSON)
        assert response.status_code == unknown.status_code == 401 and response.json() == unknown.json()
    locked = client.post("/api/auth/login", content=body, headers=RAW_JSON)
    assert locked.status_code == 429 and locked.json() == {"detail": {"code": "too_many_attempts"}}


@contextmanager
def from_ip(client, ip):
    """Client thứ hai trên CÙNG app, khác IP nguồn (không chạy lại lifespan)."""
    other = TestClient(client.app, base_url="https://testserver", headers={"X-Requested-With": "fetch"},
                       client=(ip, 50000))
    try:
        yield other
    finally:
        other.close()


def test_overlong_password_counts_as_a_failure_without_hashing(client, sign_up, monkeypatch):
    sign_up("an@example.com")
    client.cookies.clear()
    verified = []
    monkeypatch.setattr(auth_service, "verify_password", lambda *args: verified.append(args) or False)
    for _ in range(5):
        response = login(client, "an@example.com", "x" * 129)
        assert response.status_code == 401 and response.json() == {"detail": {"code": "invalid_credentials"}}
    assert verified == []
    assert login(client, "an@example.com").status_code == 429


def test_parallel_wrong_passwords_cannot_exceed_the_limit(client, sign_up, monkeypatch):
    sign_up("an@example.com")
    auth = client.app.state.auth
    entered, codes = [], []
    release = threading.Event()

    def slow_verify(password_hash, password):
        entered.append(1)
        release.wait(10)  # giữ cả 5 lượt "đang bay" cùng lúc
        return False

    monkeypatch.setattr(auth_service, "verify_password", slow_verify)

    def attempt():
        with db_of(client) as db:
            try:
                auth.login(db, "an@example.com", "sai-mat-khau", "1.2.3.4")
            except ApiError as error:
                codes.append(error.code)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 10
    while len(entered) + codes.count("too_many_attempts") < 8 and time.monotonic() < deadline:
        time.sleep(0.01)
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(entered) == 5
    assert sorted(codes) == ["invalid_credentials"] * 5 + ["too_many_attempts"] * 3


def test_per_email_cap_holds_across_client_ips(client, sign_up):
    sign_up("an@example.com")
    for index in range(20):
        with from_ip(client, f"10.0.0.{index}") as other:
            assert login(other, "an@example.com", "sai-mat-khau").status_code == 401
    with from_ip(client, "10.0.1.1") as fresh:
        blocked = login(fresh, "an@example.com")  # đúng mật khẩu, IP chưa từng sai
    assert blocked.status_code == 429 and blocked.json() == {"detail": {"code": "too_many_attempts"}}
    with from_ip(client, "10.0.1.2") as fresh:
        assert login(fresh, "binh@example.com", "sai-mat-khau").status_code == 401  # email khác không bị vạ lây


def test_successful_logins_never_trip_the_per_email_cap(client, sign_up):
    sign_up("an@example.com")
    for index in range(21):
        with from_ip(client, f"10.0.0.{index}") as other:
            assert login(other, "an@example.com").status_code == 200


def test_register_forgot_and_resend_share_a_per_ip_limit(client):
    calls = (
        [("/api/auth/register", {"email": f"moi{index}@example.com", "password": PASSWORD}) for index in range(4)]
        + [("/api/auth/forgot-password", {"email": "ai@example.com"})] * 3
        + [("/api/auth/resend-verification", {"email": "ai@example.com"})] * 3
    )
    for path, body in calls:
        assert client.post(path, json=body).status_code == 202, path
    for path, body in (calls[0], calls[4], calls[7]):
        response = client.post(path, json=body)
        assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_requests"}}, path
    assert login(client, "ai@example.com").status_code == 401  # đăng nhập không dùng chung hạn mức này
    with from_ip(client, "10.0.0.1") as other:
        assert register(other, "khac@example.com").status_code == 202


def test_successful_login_resets_the_failure_count(client, sign_up):
    sign_up("an@example.com")
    client.cookies.clear()
    for _ in range(4):
        login(client, "an@example.com", "sai-mat-khau")
    assert login(client, "an@example.com").status_code == 200
    for _ in range(4):
        login(client, "an@example.com", "sai-mat-khau")
    assert login(client, "an@example.com").status_code == 200


def test_logout_revokes_the_session_server_side(client, sign_up):
    sign_up("an@example.com")
    token = client.cookies.get("session")
    assert client.post("/api/auth/logout").status_code == 204
    assert me_with(client, token).status_code == 401


def test_logout_without_session_is_harmless(client):
    assert client.post("/api/auth/logout").status_code == 204


def test_me_includes_the_display_name(client, sign_up):
    me = sign_up("an@example.com")
    assert (me["display_name"], me["is_admin"]) == (None, False)
    assert client.get("/api/auth/me").json() == {"id": me["id"], "email": "an@example.com", "display_name": None, "is_admin": False,
                                                    "smtp_notice_dismissed": False, "advance_mode": False}


def test_me_requires_a_session(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401 and response.json() == {"detail": {"code": "unauthenticated"}}


def test_expired_session_is_rejected_and_removed(client, sign_up):
    sign_up("an@example.com")
    token = client.cookies.get("session")
    with db_of(client) as db:
        db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert me_with(client, token).status_code == 401
    with db_of(client) as db:
        assert db.scalar(select(UserSession)) is None


def test_forgot_password_never_reveals_accounts(client, mailer):
    for email in ("ai-do@example.com", "rac"):
        assert client.post("/api/auth/forgot-password", json={"email": email}).status_code == 202
    assert mailer.sent == []


def test_password_reset_revokes_sessions_and_is_single_use(client, mailer, sign_up):
    sign_up("an@example.com")
    old_session = client.cookies.get("session")
    unthrottle(client, "an@example.com")
    assert client.post("/api/auth/forgot-password", json={"email": "an@example.com"}).status_code == 202
    mail = mailer.last_to("an@example.com")
    assert "https://app.test/reset-password?token=" in mail.body
    token = token_in(mail)
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "mat-khau-moi"}).status_code == 204
    assert me_with(client, old_session).status_code == 401
    assert login(client, "an@example.com").status_code == 401
    assert login(client, "an@example.com", "mat-khau-moi").status_code == 200
    reused = client.post("/api/auth/reset-password", json={"token": token, "password": "mat-khau-khac"})
    assert reused.status_code == 400 and reused.json() == {"detail": {"code": "invalid_token"}}


def test_weak_password_does_not_burn_the_reset_token(client, mailer, sign_up):
    sign_up("an@example.com")
    unthrottle(client, "an@example.com")
    client.post("/api/auth/forgot-password", json={"email": "an@example.com"})
    token = token_in(mailer.last_to("an@example.com"))
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "ngan"}).status_code == 422
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "mat-khau-moi"}).status_code == 204


@pytest.mark.parametrize(("path", "body"), [
    ("/api/auth/verify-email", '{"token": "A\\ud800b"}'),
    ("/api/auth/reset-password", '{"token": "A\\ud800b", "password": "mat-khau-moi"}'),
    ("/api/auth/confirm-email", '{"token": "A\\ud800b"}'),
])
def test_a_token_that_is_not_valid_unicode_is_just_an_invalid_token(client, path, body):
    response = client.post(path, content=body, headers=RAW_JSON)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "invalid_token"}}


def test_password_reset_also_verifies_the_email(client, mailer):
    register(client, "an@example.com")
    unthrottle(client, "an@example.com")
    client.post("/api/auth/forgot-password", json={"email": "an@example.com"})
    token = token_in(mailer.last_to("an@example.com"))
    client.post("/api/auth/reset-password", json={"token": token, "password": "mat-khau-moi"})
    assert login(client, "an@example.com", "mat-khau-moi").status_code == 200


def test_resend_verification_only_mails_unverified_accounts(client, mailer, sign_up):
    register(client, "chua@example.com")
    sign_up("roi@example.com")
    unthrottle(client, "chua@example.com")
    unthrottle(client, "roi@example.com")
    before = len(mailer.sent)
    for email in ("chua@example.com", "roi@example.com", "khong-co@example.com"):
        assert client.post("/api/auth/resend-verification", json={"email": email}).status_code == 202
    assert [m.to for m in mailer.sent[before:]] == ["chua@example.com"]


def test_register_without_mail_creates_a_verified_account_that_signs_in_at_once(settings):
    with bare_client(settings) as client:  # không tiêm mailer, không SMTP, không MAIL_DEV_LOG → mail_enabled=false
        response = register(client, "an@example.com")
        assert response.status_code == 202 and response.json() == {"status": "accepted"}
        assert nonce_cookie_shape(response)[0] > len("verify_nonce=")  # vẫn có cookie mồi
        assert not any(c.startswith("session=") for c in response.headers.get_list("set-cookie"))  # KHÔNG tự đăng nhập
        with db_of(client) as db:
            user = db.scalar(select(User).where(User.email == "an@example.com"))
            assert user.email_verified_at is not None
            assert db.scalar(select(func.count()).select_from(EmailToken).where(EmailToken.user_id == user.id)) == 0
        assert login(client, "an@example.com").status_code == 200


def test_register_without_mail_looks_identical_for_free_and_taken_addresses(settings):
    with bare_client(settings) as client:
        first = register(client, "an@example.com")
        second = register(client, "an@example.com", "mat-khau-khac")
        assert first.status_code == second.status_code == 202 and first.json() == second.json()
        assert nonce_cookie_shape(first) == nonce_cookie_shape(second)
        assert login(client, "an@example.com").status_code == 200  # mật khẩu ĐẦU vẫn là của tài khoản
        assert login(client, "an@example.com", "mat-khau-khac").status_code == 401


def test_registration_closed_is_refused_before_the_throttle(client):
    with db_of(client) as db:
        instance_row(db).registration_open = False
        db.commit()
    for index in range(12):  # hơn hạn mức 10/15 phút/IP: cổng đóng không tốn hạn mức, không tra email, không băm
        response = register(client, f"moi{index}@example.com")
        assert response.status_code == 403 and response.json() == {"detail": {"code": "registration_closed"}}
    with db_of(client) as db:
        instance_row(db).registration_open = True
        db.commit()
    assert register(client, "mo-lai@example.com").status_code == 202


def test_forgot_and_resend_are_refused_without_mail(settings):
    with bare_client(settings) as client:
        for path in ("/api/auth/forgot-password", "/api/auth/resend-verification"):
            for email in ("co@example.com", "khong-hop-le"):  # trước mọi tra cứu / validate: điều kiện của instance
                response = client.post(path, json={"email": email})
                assert response.status_code == 409 and response.json() == {"detail": {"code": "mail_not_configured"}}, path


def test_mail_not_configured_is_refused_before_the_ip_throttle(settings):
    with bare_client(settings) as client:
        for path in ("/api/auth/forgot-password", "/api/auth/resend-verification"):
            for _ in range(11):  # hơn hạn mức 10/15 phút/IP: require_mail đứng trước throttle_by_ip, không tốn lượt
                response = client.post(path, json={"email": "ai@example.com"})
                assert response.status_code == 409 and response.json() == {"detail": {"code": "mail_not_configured"}}, path
        assert register(client, "an@example.com").status_code == 202  # hạn mức chung với đăng ký vẫn còn nguyên


def test_smtp_failure_does_not_break_registration(settings):
    class Broken:
        def send(self, mail):
            raise OSError("smtp down")

    with bare_client(settings, Broken()) as c:  # chèn sẵn admin: bảng users trống thì register 409 setup_required
        response = c.post("/api/auth/register", json={"email": "an@example.com", "password": PASSWORD})
    assert response.status_code == 202
