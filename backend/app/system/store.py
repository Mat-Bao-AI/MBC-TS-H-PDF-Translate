"""Dòng cấu hình instance (bảng instance_settings, id=1) và các giá trị "hiệu lực" suy từ DB → env (spec 2026-10-05 §4, §7)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import SMTP_SECURITIES, Settings  # noqa: F401 — re-export cho lớp Cài đặt (system.service)
from ..models import InstanceSettings
from ..providers.crypto import open_sealed, seal

SMTP_INFO = b"instance-settings/v1"  # HKDF info riêng: khoá dẫn khác khoá của API key
SMTP_AAD = b"instance:smtp"  # ciphertext không bê sang cột/bảng khác được


def instance_row(db: Session) -> InstanceSettings:
    """Migration 0005 đã chèn dòng id=1; DB thiếu dòng (tạo tay) thì chèn tại chỗ để mọi nơi đọc được."""
    row = db.get(InstanceSettings, 1)
    if row is None:
        row = InstanceSettings(id=1)
        db.add(row)
        db.commit()
    return row


def effective_pending_limit(db: Session, settings: Settings) -> int:
    """DB ghi đè env; NULL = env. Đọc mỗi lần gọi: đổi trong Cài đặt có hiệu lực ngay."""
    value = instance_row(db).max_pending_per_user
    return settings.max_pending_per_user if value is None else value


def site_url(db: Session, settings: Settings) -> tuple[str | None, str | None]:
    """Địa chỉ trang cho MỌI link trong thư → (địa chỉ, nguồn): env APP_BASE_URL ("env") > ghi lúc /setup ("setup") >
    (None, None) = chưa biết → thư coi như tắt (system.mail). Không bao giờ suy từ Host của request thường."""
    if settings.app_base_url:
        return settings.app_base_url, "env"
    recorded = instance_row(db).site_url
    return (recorded, "setup") if recorded else (None, None)


def seal_smtp_password(secret_key: str, password: str) -> str:
    return seal(secret_key, password, info=SMTP_INFO, aad=SMTP_AAD)


def open_smtp_password(secret_key: str, token: str | None) -> str | None:
    """None khi chưa lưu, hỏng, hoặc SECRET_KEY đã đổi (= password_status "unreadable")."""
    return None if token is None else open_sealed(secret_key, token, info=SMTP_INFO, aad=SMTP_AAD)
