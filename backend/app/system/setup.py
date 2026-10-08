"""Trình cài đặt lần đầu (spec 2026-10-05 §2–3): "cần cài đặt" = bảng users trống; tạo admin là MỘT câu INSERT có điều kiện."""

from __future__ import annotations

import hmac
import logging
import uuid
from urllib.parse import urlsplit

from sqlalchemy import String, exists, insert, literal, select
from sqlalchemy.orm import Session

from ..auth.account import clean_display_name
from ..auth.mailer import Mailer
from ..auth.service import check_password, normalize_email
from ..config import ConfigError, Settings, normalize_base_url
from ..db import utcnow
from ..errors import ApiError
from ..models import User
from ..security import hash_password
from .mail import resolve_mail
from .store import instance_row

log = logging.getLogger("system")


def _any_user():
    return exists().where(User.id.isnot(None))


def needs_setup(db: Session) -> bool:
    return not db.scalar(select(_any_user()))


def status_payload(db: Session, settings: Settings, injected: Mailer | None) -> dict:
    """Công khai: không có gì bí mật (needs_setup=true lộ instance trống — cũng là lúc /setup hiện ra)."""
    row = instance_row(db)
    return {"needs_setup": needs_setup(db), "setup_token_required": bool(settings.setup_token),
            "registration_open": row.registration_open, "mail_enabled": resolve_mail(db, settings, injected).enabled}


def _token_matches(expected: str, given: str | None) -> bool:
    # surrogatepass hai phía: JSON cho phép "\ud800", env giữ byte lạ dạng surrogate — không bao giờ 500, vẫn so đúng từng ký tự.
    return hmac.compare_digest(expected.encode("utf-8", "surrogatepass"), (given or "").encode("utf-8", "surrogatepass"))


def recordable_site_url(base_url: str) -> str | None:
    """Gốc `scheme://máy[:cổng]` của request /setup nếu dùng được làm địa chỉ trang trong thư — cùng phép kiểm với env
    APP_BASE_URL (https, http chỉ cho localhost); có đường dẫn / query / user@ / cổng hỏng → None."""
    try:
        url = normalize_base_url(base_url)
        parts = urlsplit(url)
        parts.port  # noqa: B018 — cổng không phải số thì ném ValueError
    except (ConfigError, ValueError):
        return None
    if not parts.hostname or parts.username is not None or parts.path or parts.query or parts.fragment:
        return None
    # `#`, `?`, `;x`, `%2F`… cuối chuỗi có thể lọt qua urlsplit (fragment/query rỗng) — chỉ nhận đúng dạng gốc, byte-từng-byte.
    if url != f"{parts.scheme}://{parts.netloc}" or any(ch in parts.netloc for ch in "?#;%\\"):
        return None
    return url


def create_admin(db: Session, settings: Settings, *, display_name: str | None, email_raw: str, password: str,
                 setup_token: str | None, base_url: str | None = None) -> User:
    if settings.setup_token and not _token_matches(settings.setup_token, setup_token):
        raise ApiError(403, "invalid_setup_token")  # TRƯỚC validate: người không có mã không học được gì thêm
    name = clean_display_name(display_name)  # 422 invalid_display_name (rỗng → None)
    email = normalize_email(email_raw)  # 422 invalid_email
    check_password(password)  # 422 invalid_password
    user_id, now = uuid.uuid4().hex, utcnow()
    # Kiểm "chưa có user" và chèn trong MỘT câu ghi (SQLite một người ghi): hai lượt song song thì đúng một lượt chèn
    # được, lượt kia rowcount 0 → 409. Không kiểm-rồi-chèn hai bước. Cột không liệt kê (default_engine, default_font…)
    # lấy default của model: from_select(include_defaults=True) thêm chúng vào INSERT và SELECT.
    columns = [User.id, User.email, User.password_hash, User.email_verified_at, User.is_admin, User.display_name,
               User.created_at]
    values = select(
        literal(user_id), literal(email), literal(hash_password(password)), literal(now), literal(True),
        literal(name, String(50)), literal(now),
    ).where(~_any_user())
    inserted = db.execute(insert(User).from_select(columns, values)).rowcount
    if not inserted:
        db.rollback()
        raise ApiError(409, "setup_done")
    row = instance_row(db)
    row.setup_completed_at = now
    if row.site_url is None and base_url is not None:
        # Ghi địa chỉ trang (kiểu "siteurl" của WordPress) cùng commit với admin. Tin được: ai hoàn tất /setup là thành
        # quản trị viên (và phải biết SETUP_TOKEN nếu có đặt), nên request này đáng tin ngang admin. KHÔNG BAO GIỜ dựng
        # link từ Host của request thường — đầu độc Host header vào link đặt lại mật khẩu.
        site_url = recordable_site_url(base_url)
        if site_url is None:
            log.warning("Cài đặt xong nhưng không ghi địa chỉ trang %r (cần https, hoặc http trên localhost) — thư có "
                        "liên kết chỉ gửi được khi có APP_BASE_URL", base_url)
        else:
            log.info("Đã ghi địa chỉ trang %s từ request /setup — nếu sai, đặt APP_BASE_URL hoặc sửa instance_settings.site_url", site_url)
        row.site_url = site_url
    db.commit()
    return db.get(User, user_id)
