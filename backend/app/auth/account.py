"""Cài đặt › Tài khoản: tên hiển thị, đổi mật khẩu, đổi email qua link, xoá tài khoản (spec 2026-10-02 §5).

Mọi thao tác nhận mật khẩu đi qua `AuthService.verify_current_password` — chung bộ đếm thử sai với đăng nhập.
Thư được trả về cho router gửi SAU phản hồi (BackgroundTasks), như các thư khác.
"""

from __future__ import annotations

import logging
import shutil
import unicodedata
from pathlib import Path

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import EmailToken, File, User, UserSession
from ..security import hash_password
from .mailer import Mail
from .service import NEW_EMAIL_TTL, AuthService, check_password, normalize_email

log = logging.getLogger("auth")

DISPLAY_NAME_MAX = 50
# Ký tự điều khiển, định dạng vô hình (zero-width, đảo chiều chữ…), surrogate lẻ (không mã hoá được UTF-8 → lỗi
# lúc ghi DB), ngắt dòng / ngắt đoạn U+2028 / U+2029 (vỡ menu avatar một dòng).
CONTROL_CATEGORIES = ("Cc", "Cf", "Cs", "Zl", "Zp")


def clean_display_name(raw: str | None) -> str | None:
    """NFC + bỏ khoảng trắng hai đầu; rỗng → None (bỏ tên). Quá 50 ký tự / có ký tự điều khiển → 422."""
    name = unicodedata.normalize("NFC", raw or "").strip()
    if not name:
        return None
    if len(name) > DISPLAY_NAME_MAX or any(unicodedata.category(ch) in CONTROL_CATEGORIES for ch in name):
        raise ApiError(422, "invalid_display_name")
    return name


def set_display_name(db: Session, user: User, raw: str | None) -> User:
    user.display_name = clean_display_name(raw)
    db.commit()
    return user


def dismiss_smtp_notice(db: Session, user: User) -> None:
    user.smtp_notice_dismissed = True  # idempotent
    db.commit()


def change_password(db: Session, auth: AuthService, user: User, current_password: str, new_password: str,
                    client_ip: str, session_token: str) -> Mail:
    check_password(new_password)  # 422 TRƯỚC khi kiểm mật khẩu hiện tại: gõ mật khẩu mới yếu không tốn lượt đếm sai
    auth.verify_current_password(user, current_password, client_ip)
    user.password_hash = hash_password(new_password)
    # Giữ phiên của chính trình duyệt này; mọi thiết bị khác phải đăng nhập lại.
    db.execute(delete(UserSession).where(UserSession.user_id == user.id,
                                         UserSession.id != auth.session_id(session_token)))
    # Link đặt lại mật khẩu / đổi email đang chờ do người biết mật khẩu CŨ xin: không còn hiệu lực.
    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.kind.in_(("reset", "new_email")),
                                        EmailToken.used_at.is_(None)))
    db.commit()
    return password_changed_mail(auth, db, user.email)


def request_email_change(db: Session, auth: AuthService, user: User, new_email_raw: str, password: str,
                         client_ip: str) -> Mail | None:
    """Phát link xác nhận tới email MỚI. Email đã có chủ (hoặc vừa gửi thư cho địa chỉ đó < 60 s) → không phát
    gì, không gửi gì, nhưng người gọi vẫn trả 202 y hệt — không dò được email nào đã đăng ký."""
    new_email = normalize_email(new_email_raw)  # 422 invalid_email — trước khi kiểm mật khẩu: gõ sai không tốn lượt
    if new_email == user.email:
        raise ApiError(400, "same_email")
    auth.verify_current_password(user, password, client_ip)
    if auth.user_by_email(db, new_email) is None and auth.may_mail(new_email):
        token = auth.issue_token(db, user, "new_email", NEW_EMAIL_TTL, new_email=new_email)  # thay link đang chờ
        db.commit()
        return email_change_mail(auth, db, new_email, token)
    # Không phát link mới nhưng vẫn huỷ link đang chờ y như nhánh trên: nếu link cũ chỉ sống sót khi địa chỉ vừa
    # xin đã có chủ, kẻ dò xin link về hộp thư mình rồi thử lại link đó (400 / 200) là biết. Chỉ giữ link cho
    # ĐÚNG địa chỉ này (bấm gửi hai lần trong 60 s: lần hai bị chặn thư, link lần một vẫn dùng được).
    db.execute(delete(EmailToken).where(
        EmailToken.user_id == user.id, EmailToken.kind == "new_email", EmailToken.used_at.is_(None),
        EmailToken.new_email.is_distinct_from(new_email),
    ))
    db.commit()
    return None


def confirm_email_change(db: Session, auth: AuthService, token: str) -> tuple[User, Mail]:
    """Bấm link trong thư (không cần đăng nhập, không tạo phiên): đổi `users.email`, báo email CŨ."""
    row = auth.consume_token(db, token, "new_email")  # 400 invalid_token; đánh dấu đã dùng
    token_hash, new_email = row.token_hash, row.new_email
    user = db.get(User, row.user_id)
    if not new_email or auth.user_by_email(db, new_email) is not None:
        db.commit()  # token coi như đã dùng: link này không bao giờ đổi được email nữa
        raise ApiError(409, "email_taken")
    # Hộp thư cũ không còn là của tài khoản: link đặt lại mật khẩu đã gửi tới đó không được dùng nữa.
    # (Xoá TRƯỚC khi gán email: câu DELETE autoflush mọi thay đổi đang chờ, kể cả email mới.)
    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.kind == "reset",
                                        EmailToken.used_at.is_(None)))
    old_email, user.email = user.email, new_email
    try:
        db.commit()
    except IntegrityError:
        # Có người đăng ký đúng email này giữa lúc kiểm và lúc ghi (UNIQUE users.email).
        db.rollback()
        burned = db.get(EmailToken, token_hash)
        if burned is not None:
            burned.used_at = utcnow()
            db.commit()
        raise ApiError(409, "email_taken") from None
    return user, email_changed_mail(old_email, new_email)


def delete_account(db: Session, auth: AuthService, settings: Settings, user: User, password: str, client_ip: str) -> None:
    auth.verify_current_password(user, password, client_ip)
    user_id = user.id
    # MỘT câu lệnh: kiểm "không có tệp đang chạy" VÀ "không phải admin duy nhất khi còn người khác" (spec 2026-10-05 §8
    # last_admin) cùng lúc với xoá — runner nhận việc bằng UPDATE có điều kiện, SQLite tuần tự hoá các câu ghi nên không
    # có khe hở giữa lúc kiểm và lúc xoá, và hai admin cùng xoá không để instance trắng admin. CASCADE (PRAGMA
    # foreign_keys=ON) xoá phiên, token, key, tệp; tệp `queued` bị xoá là không bao giờ được chạy (DB là hàng đợi).
    running = exists().where(File.user_id == user_id, File.status == "running")
    other = aliased(User)  # "người khác" trong câu con: bí danh riêng, không lẫn với dòng đang xoá
    others = exists().where(other.id != user_id)
    other_admin = exists().where(other.id != user_id, other.is_admin.is_(True))
    allowed = or_(User.is_admin.is_(False), ~others, other_admin)
    deleted = db.execute(delete(User).where(User.id == user_id, ~running, allowed)).rowcount
    db.commit()
    if not deleted:
        # Tra lại lý do theo điều kiện admin (không theo tệp: tệp có thể vừa chạy xong) — người thường không bao giờ
        # nhận `last_admin`; admin duy nhất vẫn là `last_admin` dù đang có tệp chạy (xong tệp cũng chưa xoá được).
        last_admin = db.scalar(select(exists().where(User.id == user_id, ~allowed)))
        raise ApiError(409, "last_admin" if last_admin else "file_running")
    _remove_user_data(settings.users_dir / user_id, user_id)


def _remove_user_data(path: Path, user_id: str) -> None:
    """Như `rmtree(ignore_errors=True)`: xoá được gì thì xoá và KHÔNG raise (dòng user đã commit) — nhưng thư mục
    còn sót thì ghi log để quản trị viên dọn tay."""
    errors: list[tuple[str, BaseException]] = []

    def keep_going(_function, failed_path: str, error: BaseException) -> None:
        if not isinstance(error, FileNotFoundError):  # chưa từng tải tệp nào / mục đã biến mất: không phải lỗi
            errors.append((failed_path, error))

    shutil.rmtree(path, onexc=keep_going)
    if errors:
        failed_path, error = errors[0]
        log.warning("Xoá tài khoản %s: không xoá hết %s (%d lỗi, đầu tiên ở %s: %s)",
                    user_id, path, len(errors), failed_path, error)


def password_changed_mail(auth: AuthService, db: Session, email: str) -> Mail:
    # Gửi cả khi thư "tắt" (như trước: không SMTP thì vào log): chưa biết địa chỉ trang thì bỏ link, không dựng "None/…".
    base = auth.site_url(db)
    action = (f"Nếu không phải bạn, hãy dùng Quên mật khẩu ngay: {base}/forgot-password\n" if base
              else "Nếu không phải bạn, hãy liên hệ quản trị viên ngay.\n")
    return Mail(email, "Mật khẩu PDF Translate vừa được đổi", (
        "Chào bạn,\n\n"
        "Mật khẩu tài khoản PDF Translate của bạn vừa được đổi. Các thiết bị khác đã bị đăng xuất.\n"
        f"{action}"
    ))


def email_change_mail(auth: AuthService, db: Session, new_email: str, token: str) -> Mail:
    return Mail(new_email, "Xác nhận email mới cho PDF Translate", (
        "Chào bạn,\n\n"
        "Bấm vào liên kết dưới đây để dùng email này cho tài khoản PDF Translate:\n"
        f"{auth.link(db, '/confirm-email', token)}\n\n"
        "Liên kết có hiệu lực trong 24 giờ và chỉ dùng được một lần. Email tài khoản chỉ đổi sau khi bạn bấm "
        "liên kết. Nếu bạn không yêu cầu, hãy bỏ qua thư này.\n"
    ))


def email_changed_mail(old_email: str, new_email: str) -> Mail:
    return Mail(old_email, "Email tài khoản PDF Translate đã thay đổi", (
        "Chào bạn,\n\n"
        f"Email đăng nhập của tài khoản PDF Translate vừa được đổi sang {new_email}.\n"
        "Nếu không phải bạn, hãy liên hệ quản trị viên ngay.\n"
    ))
