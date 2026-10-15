import logging
import os
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.db import utcnow
from app.engine.paths import file_dir
from app.models import ApiCredential, EmailToken, File, User, UserSession
from helpers import ADMIN_EMAIL, ADMIN_PASSWORD, bare_client, login_admin, save_key, token_in, upload, wait_file

PASSWORD = "mat-khau-8"
NEW_PASSWORD = "mat-khau-moi-9"
RAW_JSON = {"Content-Type": "application/json", "X-Requested-With": "fetch"}  # thân JSON gõ tay (surrogate lẻ…)


@pytest.fixture
def me(sign_up) -> dict:
    return sign_up("an@example.com")


def db_of(client):
    return client.app.state.session_factory()


def login(client, email="an@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def change_password(client, current=PASSWORD, new=NEW_PASSWORD):
    return client.post("/api/account/password", json={"current_password": current, "new_password": new})


def delete_account(client, password=PASSWORD):
    return client.post("/api/account/delete", json={"password": password})


def add_token(client, user_id, kind) -> str:
    """Token đang chờ chèn thẳng vào DB (đổi email qua API có ở Task 5)."""
    token_hash = f"{kind}-{user_id}"[:64]
    with db_of(client) as db:
        db.add(EmailToken(token_hash=token_hash, user_id=user_id, kind=kind,
                          expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    return token_hash


def pending_kinds(client, user_id) -> set[str]:
    with db_of(client) as db:
        rows = db.scalars(select(EmailToken).where(EmailToken.user_id == user_id, EmailToken.used_at.is_(None))).all()
        return {row.kind for row in rows}


# ---- Thông báo SMTP đã đóng -------------------------------------------------------------------

def test_dismissing_the_smtp_notice_is_remembered_on_the_account(client, me):
    assert me["smtp_notice_dismissed"] is False
    assert client.post("/api/account/notices/smtp/dismiss").status_code == 204
    assert client.get("/api/auth/me").json()["smtp_notice_dismissed"] is True
    assert client.post("/api/account/notices/smtp/dismiss").status_code == 204  # lặp lại vô hại
    assert client.get("/api/auth/me").json()["smtp_notice_dismissed"] is True
    client.cookies.clear()
    assert login(client).json()["smtp_notice_dismissed"] is True  # theo tài khoản: đăng nhập lại/thiết bị khác vẫn thấy


def test_dismissing_the_smtp_notice_needs_a_session_and_the_csrf_header(client, me):
    assert client.post("/api/account/notices/smtp/dismiss", headers={"X-Requested-With": ""}).status_code == 403
    assert client.get("/api/auth/me").json()["smtp_notice_dismissed"] is False
    client.cookies.clear()
    response = client.post("/api/account/notices/smtp/dismiss")
    assert response.status_code == 401


# ---- Tên hiển thị -----------------------------------------------------------------------------

def test_profile_trims_and_saves_the_display_name(client, me):
    response = client.put("/api/account/profile", json={"display_name": "  Nguyễn Văn Cường  "})
    assert response.status_code == 200
    assert response.json() == {"id": me["id"], "email": "an@example.com", "display_name": "Nguyễn Văn Cường", "is_admin": False,
                                "smtp_notice_dismissed": False, "advance_mode": False}
    assert client.get("/api/auth/me").json()["display_name"] == "Nguyễn Văn Cường"
    fifty = "x" * 50
    assert client.put("/api/account/profile", json={"display_name": fifty}).json()["display_name"] == fifty


def test_a_blank_display_name_removes_it(client, me):
    client.put("/api/account/profile", json={"display_name": "Cường"})
    for blank in ("", "   ", None):
        response = client.put("/api/account/profile", json={"display_name": blank})
        assert response.status_code == 200 and response.json()["display_name"] is None


@pytest.mark.parametrize("name", ["x" * 51, "An\x00na", "An‮na", "An\u2028na", "An\u2029na"])
def test_display_name_rejects_overlong_names_and_control_characters(client, me, name):
    response = client.put("/api/account/profile", json={"display_name": name})
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_display_name"}}
    assert client.get("/api/auth/me").json()["display_name"] is None


def test_display_name_rejects_a_lone_surrogate(client, me):
    """`\\ud800` hợp lệ trong JSON nhưng không mã hoá được UTF-8: phải là 422, không phải 500 lúc ghi DB."""
    response = client.put("/api/account/profile", content='{"display_name": "A\\ud800b"}', headers=RAW_JSON)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_display_name"}}
    assert client.get("/api/auth/me").json()["display_name"] is None


# ---- Đổi mật khẩu -----------------------------------------------------------------------------

def as_session(token: str) -> dict:
    return {"Cookie": f"session={token}"}


def test_change_password_keeps_this_session_and_signs_out_the_others(client, me):
    this_device = client.cookies.get("session")
    other_device = login(client).cookies.get("session")  # cùng tài khoản đăng nhập ở "thiết bị khác"
    client.cookies.clear()
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert client.post("/api/account/password", json=body, headers=as_session(this_device)).status_code == 204
    assert client.get("/api/auth/me", headers=as_session(this_device)).status_code == 200  # phiên đang dùng vẫn sống
    assert client.get("/api/auth/me", headers=as_session(other_device)).status_code == 401
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_change_password_cancels_pending_reset_and_email_change_links(client, me):
    add_token(client, me["id"], "reset")
    add_token(client, me["id"], "new_email")
    assert pending_kinds(client, me["id"]) == {"reset", "new_email"}
    assert change_password(client).status_code == 204
    assert pending_kinds(client, me["id"]) == set()


def test_change_password_mails_the_current_address(client, me, mailer):
    assert change_password(client).status_code == 204
    mail = mailer.last_to("an@example.com")
    assert mail.subject == "Mật khẩu PDF Translate vừa được đổi"
    assert "https://app.test/forgot-password" in mail.body and "token=" not in mail.body


def test_change_password_rejects_a_wrong_current_password(client, me, mailer):
    sent = len(mailer.sent)
    response = change_password(client, current="sai-mat-khau")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "wrong_password"}}
    assert len(mailer.sent) == sent
    client.cookies.clear()
    assert login(client).status_code == 200  # mật khẩu cũ vẫn dùng được


@pytest.mark.parametrize("new", ["ngan", "x" * 129])
def test_a_weak_new_password_is_refused_before_the_current_one_is_checked(client, me, new):
    for _ in range(6):  # không tính là lần sai: 6 lần vẫn không bị khoá
        response = change_password(client, current="sai-mat-khau", new=new)
        assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_password"}}
    client.cookies.clear()
    assert login(client).status_code == 200


def test_a_new_password_that_is_not_valid_unicode_is_refused(client, me):
    body = f'{{"current_password": "{PASSWORD}", "new_password": "A\\ud800bcdefgh"}}'
    response = client.post("/api/account/password", content=body, headers=RAW_JSON)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_password"}}
    client.cookies.clear()
    assert login(client).status_code == 200


# ---- Giới hạn thử sai dùng chung với đăng nhập ------------------------------------------------

def test_wrong_passwords_share_the_login_limit(client, me):
    for _ in range(2):
        assert change_password(client, current="sai-mat-khau").status_code == 400
    for _ in range(3):
        assert delete_account(client, "sai-mat-khau").status_code == 400
    blocked = change_password(client)  # đúng mật khẩu nhưng cặp IP + email đã chạm 5 lần sai
    assert blocked.status_code == 429 and blocked.json() == {"detail": {"code": "too_many_attempts"}}
    session = client.cookies.get("session")
    client.cookies.clear()
    locked = login(client)
    assert locked.status_code == 429 and locked.json() == {"detail": {"code": "too_many_attempts"}}
    assert client.get("/api/auth/me", headers=as_session(session)).status_code == 200  # khoá thử mật khẩu, không đá phiên


def test_login_failures_also_lock_the_account_forms(client, me):
    session = client.cookies.get("session")
    client.cookies.clear()
    for _ in range(5):
        assert login(client, password="sai-mat-khau").status_code == 401
    blocked = client.post("/api/account/delete", json={"password": PASSWORD}, headers=as_session(session))
    assert blocked.status_code == 429
    with db_of(client) as db:
        assert db.get(User, me["id"]) is not None


def test_a_correct_password_clears_the_failure_count(client, me):
    for _ in range(4):
        assert delete_account(client, "sai-mat-khau").status_code == 400
    assert change_password(client).status_code == 204  # đúng → xoá đếm như đăng nhập
    client.cookies.clear()
    for _ in range(4):
        assert login(client, password="sai-mat-khau").status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200  # 4 + 4 lần sai nhưng không bị khoá


# ---- Xoá tài khoản ----------------------------------------------------------------------------

def test_delete_requires_the_right_password(client, me):
    response = delete_account(client, "sai-mat-khau")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "wrong_password"}}
    assert client.get("/api/auth/me").status_code == 200


def test_delete_refuses_while_a_file_is_running(client, me, settings):
    running = upload(client, "slow.pdf").json()["id"]  # worker giả ngủ 3 s
    queued = upload(client, "doc.pdf").json()["id"]
    wait_file(client, running, statuses=("running",))
    response = delete_account(client)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "file_running"}}
    assert "session=" not in response.headers.get("set-cookie", "")
    with db_of(client) as db:
        assert db.get(User, me["id"]) is not None
        assert db.get(File, queued) is not None  # không xoá gì, kể cả tệp đang chờ
    assert file_dir(settings.users_dir, me["id"], queued).is_dir()
    assert client.get("/api/auth/me").status_code == 200
    wait_file(client, running)
    wait_file(client, queued)


def test_delete_removes_everything_and_signs_out(client, me, settings, sign_up):
    save_key(client, "gemini")
    file_id = upload(client, "doc.pdf", engine="google_free").json()["id"]
    wait_file(client, file_id)
    add_token(client, me["id"], "reset")
    session = client.cookies.get("session")
    response = delete_account(client)
    assert response.status_code == 204
    cleared = [c.lower() for c in response.headers.get_list("set-cookie") if c.startswith("session=")]
    assert cleared and "max-age=0" in cleared[0]
    assert not (settings.users_dir / me["id"]).exists()
    with db_of(client) as db:
        assert db.get(User, me["id"]) is None
        for model in (UserSession, EmailToken, File, ApiCredential):
            assert db.scalar(select(func.count()).select_from(model).where(model.user_id == me["id"])) == 0
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Cookie": f"session={session}"}).status_code == 401
    assert login(client).status_code == 401
    client.app.state.auth.mail_throttle.reset("an@example.com")
    assert sign_up("an@example.com")["email"] == "an@example.com"  # email được giải phóng, đăng ký lại được


@pytest.mark.skipif(os.geteuid() == 0, reason="root xoá được cả mục trong thư mục chỉ đọc")
def test_delete_logs_a_data_folder_it_cannot_remove(client, me, settings, caplog):
    user_dir = settings.users_dir / me["id"]
    (user_dir / "khoa").mkdir(parents=True, exist_ok=True)
    (user_dir / "khoa" / "a.pdf").write_bytes(b"x")
    user_dir.chmod(0o500)  # không xoá được thư mục con
    try:
        with caplog.at_level(logging.WARNING, logger="auth"):
            response = delete_account(client)
    finally:
        user_dir.chmod(0o700)
    assert response.status_code == 204  # dòng user đã commit: không bao giờ 500 vì đĩa
    with db_of(client) as db:
        assert db.get(User, me["id"]) is None
    [record] = [r for r in caplog.records if r.name == "auth"]
    assert record.levelno == logging.WARNING
    assert me["id"] in record.getMessage() and "Errno 13" in record.getMessage()


def test_delete_without_a_data_folder_logs_nothing(client, me, settings, caplog):
    assert not (settings.users_dir / me["id"]).exists()  # chưa từng tải tệp nào
    with caplog.at_level(logging.WARNING, logger="auth"):
        assert delete_account(client).status_code == 204
    assert [r for r in caplog.records if r.name == "auth"] == []


def test_email_change_is_refused_without_mail_before_checking_the_password(settings):
    with bare_client(settings) as client:
        login_admin(client)
        response = client.post("/api/account/email", json={"new_email": "moi@example.com", "password": "sai-mat-khau"})
        assert response.status_code == 409 and response.json() == {"detail": {"code": "mail_not_configured"}}
        for _ in range(5):  # 5 lượt 409 không tính là 5 lần sai mật khẩu
            client.post("/api/account/email", json={"new_email": "moi@example.com", "password": "sai-mat-khau"})
        assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200


def test_the_only_admin_cannot_delete_the_account_while_others_exist(client, me, sign_up):
    sign_up("binh@example.com")
    with db_of(client) as db:
        db.execute(update(User).values(is_admin=(User.id == me["id"])))  # đúng một admin: tôi
        db.commit()
    login(client)
    response = delete_account(client)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "last_admin"}}
    with db_of(client) as db:
        assert db.get(User, me["id"]) is not None and client.get("/api/auth/me").status_code == 200
    assert delete_account(client, "sai-mat-khau").status_code == 400  # mật khẩu vẫn kiểm trước
    login(client, "binh@example.com")
    assert delete_account(client).status_code == 204  # người thường xoá bình thường
    sign_up("cuong@example.com")
    with db_of(client) as db:
        db.execute(update(User).where(User.email == "cuong@example.com").values(is_admin=True))  # có admin khác
        db.commit()
    login(client)
    assert delete_account(client).status_code == 204
    with db_of(client) as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) == 1


def add_running_file(client, user_id) -> None:
    """Dòng `running` chèn thẳng DB: dừng runner thật trước (nó poll mỗi 1 s và sẽ nhận / sửa dòng chèn tay)."""
    client.app.state.runner.stop()
    with db_of(client) as db:
        db.add(File(id="chay00000001", user_id=user_id, filename="a.pdf", search_name="a.pdf", language="vi",
                    status="running"))
        db.commit()


def test_the_only_admin_with_a_running_file_gets_last_admin(client, me):
    admin_id = login_admin(client)["id"]  # admin duy nhất; `me` là người thường
    add_running_file(client, admin_id)
    response = delete_account(client, ADMIN_PASSWORD)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "last_admin"}}  # xong tệp cũng chưa xoá được
    with db_of(client) as db:
        assert db.get(User, admin_id) is not None


def test_an_admin_with_another_admin_and_a_running_file_gets_file_running(client, me):
    with db_of(client) as db:
        db.execute(update(User).where(User.id == me["id"]).values(is_admin=True))  # có admin khác
        db.commit()
    admin_id = login_admin(client)["id"]
    add_running_file(client, admin_id)
    response = delete_account(client, ADMIN_PASSWORD)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "file_running"}}
    with db_of(client) as db:
        assert db.get(User, admin_id) is not None


def test_the_last_user_can_delete_the_account_even_as_admin(settings):
    with bare_client(settings) as client:  # chỉ có admin@example.com
        login_admin(client)
        assert client.post("/api/account/delete", json={"password": ADMIN_PASSWORD}).status_code == 204
        with client.app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(User)) == 0  # instance quay lại "cần cài đặt" (spec §2)


# ---- Đổi email --------------------------------------------------------------------------------

def request_change(client, new_email="moi@example.com", password=PASSWORD):
    return client.post("/api/account/email", json={"new_email": new_email, "password": password})


def confirm(client, token):
    return client.post("/api/auth/confirm-email", json={"token": token})


def test_email_change_sends_a_link_to_the_new_address_only(client, me, mailer):
    sent = len(mailer.sent)
    response = request_change(client, "  Moi@Example.COM ")
    assert response.status_code == 202 and response.json() == {"status": "accepted"}
    [mail] = mailer.sent[sent:]
    assert mail.to == "moi@example.com" and mail.subject == "Xác nhận email mới cho PDF Translate"
    assert "https://app.test/confirm-email?token=" in mail.body and "24 giờ" in mail.body
    assert client.get("/api/auth/me").json()["email"] == "an@example.com"  # chưa đổi tới khi bấm link
    with db_of(client) as db:
        [row] = db.scalars(select(EmailToken).where(EmailToken.kind == "new_email")).all()
        assert row.new_email == "moi@example.com" and row.user_id == me["id"]


def test_email_change_looks_the_same_when_the_address_is_taken(client, me, mailer, sign_up):
    sign_up("da-co@example.com")  # client chuyển sang tài khoản khác…
    client.cookies.clear()
    assert login(client).status_code == 200  # …rồi đăng nhập lại tài khoản an@
    sent = len(mailer.sent)
    fresh = request_change(client, "moi@example.com")
    taken = request_change(client, "da-co@example.com")
    assert fresh.status_code == taken.status_code == 202
    assert fresh.json() == taken.json() == {"status": "accepted"}
    assert "set-cookie" not in fresh.headers and "set-cookie" not in taken.headers
    assert [mail.to for mail in mailer.sent[sent:]] == ["moi@example.com"]  # địa chỉ đã có chủ không nhận gì
    with db_of(client) as db:
        news = db.scalars(select(EmailToken.new_email).where(EmailToken.kind == "new_email")).all()
        assert news == []  # không phát gì cho da-co@; link tới moi@ bị huỷ y như khi xin một địa chỉ còn trống


def test_asking_for_a_taken_address_cancels_the_pending_link(client, me, mailer, sign_up):
    """Link cũ phải chết như khi xin địa chỉ còn trống — không thì thử link cũ (400 / 200) là dò được email."""
    sign_up("da-co@example.com")
    client.cookies.clear()
    assert login(client).status_code == 200
    request_change(client, "moi@example.com")
    token = token_in(mailer.last_to("moi@example.com"))
    assert request_change(client, "da-co@example.com").status_code == 202
    response = confirm(client, token)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "invalid_token"}}
    assert pending_kinds(client, me["id"]) == set()
    assert client.get("/api/auth/me").json()["email"] == "an@example.com"


def test_asking_for_a_throttled_address_cancels_the_pending_link(client, me, mailer):
    request_change(client, "w@example.com")  # vừa gửi thư tới w@: w@ bị chặn thư 60 s
    request_change(client, "moi@example.com")
    token = token_in(mailer.last_to("moi@example.com"))
    sent = len(mailer.sent)
    assert request_change(client, "w@example.com").status_code == 202  # còn trống nhưng bị chặn thư
    assert len(mailer.sent) == sent
    assert confirm(client, token).status_code == 400
    assert pending_kinds(client, me["id"]) == set()


def test_a_double_submit_keeps_the_first_link(client, me, mailer):
    assert request_change(client).status_code == 202
    token = token_in(mailer.last_to("moi@example.com"))
    sent = len(mailer.sent)
    assert request_change(client).status_code == 202  # cùng địa chỉ trong 60 s: bị chặn thư, không phát link mới
    assert len(mailer.sent) == sent
    response = confirm(client, token)
    assert response.status_code == 200 and response.json()["email"] == "moi@example.com"


def test_a_password_that_is_not_valid_unicode_is_just_a_wrong_password(client, me, mailer):
    sent = len(mailer.sent)
    body = '{"new_email": "moi@example.com", "password": "A\\ud800bcdefgh"}'
    response = client.post("/api/account/email", content=body, headers=RAW_JSON)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "wrong_password"}}
    assert len(mailer.sent) == sent


@pytest.mark.parametrize(("new_email", "password", "status", "code"), [
    ("khong-phai-email", PASSWORD, 422, "invalid_email"),
    ("AN@example.com", PASSWORD, 400, "same_email"),
    ("moi@example.com", "sai-mat-khau", 400, "wrong_password"),
])
def test_email_change_validates_input(client, me, mailer, new_email, password, status, code):
    sent = len(mailer.sent)
    response = request_change(client, new_email, password)
    assert response.status_code == status and response.json() == {"detail": {"code": code}}
    assert len(mailer.sent) == sent


def test_confirm_changes_the_email_and_warns_the_old_address(client, me, mailer):
    request_change(client)
    token = token_in(mailer.last_to("moi@example.com"))
    response = confirm(client, token)
    assert response.status_code == 200
    assert response.json() == {"id": me["id"], "email": "moi@example.com", "display_name": None, "is_admin": False,
                                "smtp_notice_dismissed": False, "advance_mode": False}
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").json()["email"] == "moi@example.com"  # phiên đang có vẫn dùng được
    warning = mailer.last_to("an@example.com")
    assert warning.subject == "Email tài khoản PDF Translate đã thay đổi"
    assert "moi@example.com" in warning.body and "liên hệ quản trị viên" in warning.body
    client.cookies.clear()
    assert login(client).status_code == 401
    assert login(client, "moi@example.com").status_code == 200
    with db_of(client) as db:
        assert db.get(User, me["id"]).email_verified_at is not None


def test_confirm_refuses_an_address_taken_meanwhile(client, me, mailer, sign_up):
    request_change(client, "tranh@example.com")
    token = token_in(mailer.last_to("tranh@example.com"))
    client.app.state.auth.mail_throttle.reset("tranh@example.com")
    sign_up("tranh@example.com")  # người khác đăng ký đúng email đó trước khi link được bấm
    client.cookies.clear()
    response = confirm(client, token)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "email_taken"}}
    assert login(client).status_code == 200  # email cũ còn nguyên
    again = confirm(client, token)
    assert again.status_code == 400 and again.json() == {"detail": {"code": "invalid_token"}}  # token coi như đã dùng
    client.cookies.clear()
    assert login(client, "tranh@example.com").status_code == 200  # tài khoản của người kia không bị ảnh hưởng


def test_confirm_survives_a_registration_racing_the_write(client, me, mailer, monkeypatch, sign_up):
    """Kiểm trùng xong mà người khác chèn đúng email đó trước lúc ghi: UNIQUE chặn → 409, token bị đốt."""
    request_change(client, "dua@example.com")
    token = token_in(mailer.last_to("dua@example.com"))
    client.app.state.auth.mail_throttle.reset("dua@example.com")
    sign_up("dua@example.com")
    auth = client.app.state.auth
    monkeypatch.setattr(auth, "user_by_email", lambda db, email: None)  # lượt kiểm "chưa thấy" người kia
    client.cookies.clear()
    response = confirm(client, token)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "email_taken"}}
    assert confirm(client, token).status_code == 400
    assert login(client).status_code == 200


def test_confirm_link_works_once(client, me, mailer):
    request_change(client)
    token = token_in(mailer.last_to("moi@example.com"))
    assert confirm(client, token).status_code == 200
    again = confirm(client, token)
    assert again.status_code == 400 and again.json() == {"detail": {"code": "invalid_token"}}


def test_confirm_rejects_other_links_and_expired_ones(client, me, mailer):
    client.app.state.auth.mail_throttle.reset("an@example.com")
    client.post("/api/auth/forgot-password", json={"email": "an@example.com"})
    reset_token = token_in(mailer.last_to("an@example.com"))
    assert confirm(client, reset_token).status_code == 400  # link đặt lại mật khẩu không đổi được email
    request_change(client)
    token = token_in(mailer.last_to("moi@example.com"))
    with db_of(client) as db:
        for row in db.scalars(select(EmailToken).where(EmailToken.kind == "new_email")):
            row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    expired = confirm(client, token)
    assert expired.status_code == 400 and expired.json() == {"detail": {"code": "invalid_token"}}


def test_confirm_needs_no_session_and_creates_none(client, me, mailer):
    request_change(client)
    token = token_in(mailer.last_to("moi@example.com"))
    client.cookies.clear()  # mở link ở trình duyệt khác
    response = confirm(client, token)
    assert response.status_code == 200 and response.json()["email"] == "moi@example.com"
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401


def test_confirm_cancels_reset_links_sent_to_the_old_address(client, me, mailer):
    client.app.state.auth.mail_throttle.reset("an@example.com")
    client.post("/api/auth/forgot-password", json={"email": "an@example.com"})
    reset_token = token_in(mailer.last_to("an@example.com"))
    request_change(client)
    assert confirm(client, token_in(mailer.last_to("moi@example.com"))).status_code == 200
    dead = client.post("/api/auth/reset-password", json={"token": reset_token, "password": "mat-khau-khac"})
    assert dead.status_code == 400 and dead.json() == {"detail": {"code": "invalid_token"}}


def test_a_password_change_cancels_a_pending_email_change(client, me, mailer):
    request_change(client)
    token = token_in(mailer.last_to("moi@example.com"))
    assert change_password(client).status_code == 204
    assert confirm(client, token).status_code == 400
    assert client.get("/api/auth/me").json()["email"] == "an@example.com"


def test_wrong_passwords_on_the_email_form_count_toward_the_login_limit(client, me):
    for _ in range(5):
        assert request_change(client, password="sai-mat-khau").status_code == 400
    assert request_change(client).status_code == 429
    client.cookies.clear()
    assert login(client).status_code == 429


# ---- Chung ------------------------------------------------------------------------------------

@pytest.mark.parametrize(("method", "path", "body"), [
    ("PUT", "/api/account/profile", {"display_name": "A"}),
    ("POST", "/api/account/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD}),
    ("POST", "/api/account/delete", {"password": PASSWORD}),
    ("POST", "/api/account/email", {"new_email": "moi@example.com", "password": PASSWORD}),
])
def test_account_endpoints_need_a_session_and_the_fetch_header(client, me, method, path, body):
    no_header = client.request(method, path, json=body, headers={"X-Requested-With": ""})
    assert no_header.status_code == 403 and no_header.json() == {"detail": {"code": "csrf"}}
    client.cookies.clear()
    anonymous = client.request(method, path, json=body)
    assert anonymous.status_code == 401 and anonymous.json() == {"detail": {"code": "unauthenticated"}}
