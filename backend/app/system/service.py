"""Cài đặt › Hệ thống (spec 2026-10-05 §4, §8): SMTP trong DB ghi đè env, công tắc đăng ký, hạn chờ, thư thử."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.utils import parseaddr

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session

from ..auth.mailer import Mail, Mailer, SmtpMailer
from ..config import Settings, default_smtp_port
from ..db import utcnow
from ..errors import ApiError
from ..models import InstanceSettings, User
from .mail import resolve_mail
from .store import SMTP_SECURITIES, instance_row, open_smtp_password, seal_smtp_password, site_url

log = logging.getLogger("system")

HOST_MAX, USERNAME_MAX, FROM_MAX = 253, 254, 254
LIMIT_MIN, LIMIT_MAX = 1, 100
REASON_MAX = 200
TEST_SUBJECT = "Thư thử từ PDF Translate"  # nháp — BA duyệt
TEST_BODY = "Chào bạn,\n\nĐây là thư thử từ PDF Translate. Nhận được thư này nghĩa là cấu hình SMTP đã đúng.\n"


@dataclass(frozen=True)
class SmtpInput:
    host: str
    port: int
    security: str
    username: str  # "" = không đăng nhập SMTP
    # None = ô để trống → dùng lại mật khẩu đã lưu (DB, không thì env) CHỈ khi host + security trùng nơi nó thuộc về
    # (xem _password_for); không trùng → coi như chưa có mật khẩu (có username → 422 invalid_smtp field=password).
    password: str | None
    sender: str


def _invalid(field: str) -> ApiError:
    return ApiError(422, "invalid_smtp", field=field)


def clean_smtp(raw: dict) -> SmtpInput:
    """Kiểm từng ô theo §8; lỗi → 422 invalid_smtp kèm `field` để UI hiện dưới đúng ô. Không ghi gì."""
    host = str(raw.get("host") or "").strip()
    if not 1 <= len(host) <= HOST_MAX or any(ch.isspace() or not ch.isprintable() for ch in host):
        raise _invalid("host")
    port = raw.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise _invalid("port")
    security = str(raw.get("security") or "").strip().lower()
    if security not in SMTP_SECURITIES:
        raise _invalid("security")
    username = str(raw.get("username") or "").strip()
    if len(username) > USERNAME_MAX or not username.isprintable():
        raise _invalid("username")
    sender = str(raw.get("from") or "").strip()
    address = parseaddr(sender)[1]  # chấp nhận "Tên <địa chỉ>" như SMTP_FROM trong env; nhiều địa chỉ → "" (bị từ chối)
    try:
        if not sender or len(sender) > FROM_MAX or not sender.isprintable() or not address:
            raise EmailNotValidError("empty")
        validate_email(address, check_deliverability=False)
    except EmailNotValidError:
        raise _invalid("from") from None
    password = raw.get("password")
    if password is not None and not isinstance(password, str):
        raise _invalid("password")
    return SmtpInput(host, port, security, username, password or None, sender)


def _password_status(settings: Settings, row: InstanceSettings) -> str:
    if row.smtp_password_enc is None:
        return "none"
    return "unreadable" if open_smtp_password(settings.secret_key, row.smtp_password_enc) is None else "saved"


def smtp_payload(db: Session, settings: Settings, injected: Mailer | None) -> dict:
    """Form điền sẵn giá trị ĐANG CÓ HIỆU LỰC (DB hoặc env); không bao giờ có mật khẩu."""
    row = instance_row(db)
    source = resolve_mail(db, settings, injected).source
    if row.smtp_host:
        security = row.smtp_security or "starttls"  # mặc định như mailer (system.mail._from_row)
        return {"source": source, "host": row.smtp_host, "port": row.smtp_port or default_smtp_port(security),
                "security": security, "username": row.smtp_username or "", "from": row.smtp_from or "",
                "password_status": _password_status(settings, row)}
    return {"source": source, "host": settings.smtp_host, "port": settings.smtp_port, "security": settings.smtp_security,
            "username": settings.smtp_user, "from": settings.smtp_from,
            "password_status": "saved" if settings.smtp_host and settings.smtp_password else "none"}


def settings_payload(db: Session, settings: Settings, injected: Mailer | None) -> dict:
    row = instance_row(db)
    url, url_source = site_url(db, settings)  # chỉ đọc: đổi bằng env APP_BASE_URL, không có ô sửa
    return {"smtp": smtp_payload(db, settings, injected), "registration_open": row.registration_open,
            "max_pending_per_user": row.max_pending_per_user, "max_pending_default": settings.max_pending_per_user,
            "site_url": url, "site_url_source": url_source}


def _password_for(settings: Settings, row: InstanceSettings, given: SmtpInput) -> str:
    """Mật khẩu đi cùng `given` — MỘT chỗ cho cả PUT lẫn thư thử. Ô có gõ → ô. Ô trống → mật khẩu đã lưu (của DB khi DB
    có cấu hình SMTP, không thì env SMTP_PASSWORD), CHỈ KHI host (không phân biệt hoa thường) và security của form trùng
    đúng nơi mật khẩu đó thuộc về: không thì admin trỏ host sang máy khác / hạ xuống `none` là nhận được nó qua AUTH.
    Không có mật khẩu dùng được → "" (không đăng nhập SMTP), riêng khi có username → 422 invalid_smtp field=password."""
    if given.password:
        return given.password
    if row.smtp_host:
        host, security = row.smtp_host, row.smtp_security or "starttls"
        stored = open_smtp_password(settings.secret_key, row.smtp_password_enc)  # None: chưa lưu / không giải mã được
    else:
        host, security, stored = settings.smtp_host, settings.smtp_security, settings.smtp_password or None
    if given.host.lower() != host.strip().lower() or given.security != security:
        stored = None
    if stored is None and given.username:
        raise _invalid("password")  # không lưu / không thử trạng thái sẽ AUTH bằng mật khẩu rỗng
    return stored or ""


def update_settings(db: Session, settings: Settings, injected: Mailer | None, *, smtp: dict | None,
                    registration_open: bool | None, max_pending: object, max_pending_set: bool) -> dict:
    """Trường bỏ qua = giữ nguyên. Kiểm HẾT rồi mới ghi: một ô sai thì cả thẻ không đổi gì."""
    if max_pending_set and max_pending is not None and (
            isinstance(max_pending, bool) or not isinstance(max_pending, int) or not LIMIT_MIN <= max_pending <= LIMIT_MAX):
        raise ApiError(422, "invalid_limit")
    row = instance_row(db)
    if smtp is not None:
        given = clean_smtp(smtp)
        password = _password_for(settings, row, given)
        row.smtp_host, row.smtp_port, row.smtp_security = given.host, given.port, given.security
        row.smtp_username, row.smtp_from = given.username or None, given.sender
        # Mật khẩu luôn đi cùng host+security nó thuộc về: gõ mới, giữ của chính máy chủ này (ô trống trên form điền từ
        # env → chép mật khẩu env vào DB, từ giờ DB ghi đè env), hoặc bỏ hẳn khi đổi sang host/security khác.
        row.smtp_password_enc = seal_smtp_password(settings.secret_key, password) if password else None
    if registration_open is not None:
        row.registration_open = registration_open
    if max_pending_set:
        row.max_pending_per_user = max_pending
    row.updated_at = utcnow()
    db.commit()
    return settings_payload(db, settings, injected)


def clear_smtp(db: Session) -> None:
    """DELETE …/smtp: sáu cột smtp_* về NULL → nguồn quay về env / none ngay thư kế tiếp."""
    row = instance_row(db)
    row.smtp_host = row.smtp_port = row.smtp_security = row.smtp_username = row.smtp_password_enc = row.smtp_from = None
    row.updated_at = utcnow()
    db.commit()


def _mask(text: str, secret: str | None) -> str:
    """Thay mật khẩu bằng ***, cả dạng chữ lẫn dạng repr: thông điệp lỗi smtplib thường là bytes (b'…\\xe1…')."""
    if not secret:
        return text
    for form in sorted({secret, repr(secret)[1:-1], repr(secret.encode())[2:-1]}, key=len, reverse=True):
        text = text.replace(form, "***")
    return text


def send_test_mail(db: Session, settings: Settings, injected: Mailer | None, admin: User, smtp: dict | None) -> str:
    """Gửi ĐỒNG BỘ (timeout 15 s của SmtpMailer) tới email của chính admin đang đăng nhập (không nhận địa chỉ tuỳ ý).
    Có `smtp` → thử đúng giá trị trong form (chưa lưu; mật khẩu trống = mật khẩu đã lưu của đúng host+security đó, xem
    _password_for); không → cấu hình hiệu lực; `none` → 409. Lỗi → 502 smtp_failed, reason = tên lớp + thông điệp
    ≤ 200 ký tự, chuỗi mật khẩu thay bằng ***."""
    if smtp is not None:
        given = clean_smtp(smtp)
        password = _password_for(settings, instance_row(db), given)
        mailer: Mailer = SmtpMailer(given.host, given.port, given.username, password, given.sender, given.security)
    else:
        setup = resolve_mail(db, settings, injected)
        if not setup.configured:  # không cần địa chỉ trang: thư thử không có liên kết
            raise ApiError(409, "mail_not_configured")
        mailer = setup.mailer
        password = getattr(mailer, "password", None) or None
    try:
        mailer.send(Mail(admin.email, TEST_SUBJECT, TEST_BODY))
    except Exception as error:  # noqa: BLE001 - mọi lỗi SMTP/mạng/DNS đều thành 502 có lý do, không 500
        reason = _mask(f"{type(error).__name__}: {error}", password)[:REASON_MAX]
        log.warning("Thư thử tới %s thất bại: %s", admin.email, type(error).__name__)  # không host, không mật khẩu
        raise ApiError(502, "smtp_failed", reason=reason) from None
    return admin.email
