"""Mailer theo cấu hình HIỆU LỰC, giải LÚC GỬI (spec 2026-10-05 §9): DB → env → MAIL_DEV_LOG → log.

Không còn `app.state.mailer` dựng một lần: admin đổi SMTP trong Cài đặt là thư kế tiếp dùng ngay, không khởi động lại.
Mailer tiêm vào `create_app(mailer=…)` (test) thay cho MỌI nguồn và tính là đã cấu hình — như MAIL_DEV_LOG.
"Có thư" (`enabled`) = có đường gửi VÀ biết địa chỉ trang để dựng link (store.site_url) — thiếu một trong hai thì mọi
nơi hỏi `enabled` (đăng ký, quên mật khẩu, đổi email, mail_enabled, dải nhắc SMTP) chạy như chế độ không SMTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy.orm import Session

from ..auth.mailer import LogMailer, Mail, Mailer, SmtpMailer, deliver, mailer_from_settings
from ..config import Settings, default_smtp_port
from ..models import InstanceSettings
from .store import instance_row, open_smtp_password, site_url

SOURCES = ("settings", "env", "dev_log", "none")
log = logging.getLogger("mailer")


@dataclass(frozen=True)
class MailSetup:
    mailer: Mailer
    source: str  # settings | env | dev_log | none
    site_url: str | None = None  # None = chưa biết địa chỉ trang (không APP_BASE_URL, /setup không ghi được)

    @property
    def configured(self) -> bool:
        """Có đường gửi — đủ cho thư thử (không có liên kết)."""
        return self.source != "none"

    @property
    def enabled(self) -> bool:
        """Đóng an toàn: không biết địa chỉ trang thì không phát link nào (thư xác nhận / đặt lại / đổi email)."""
        return self.configured and self.site_url is not None


def _from_row(settings: Settings, row: InstanceSettings) -> SmtpMailer:
    security = row.smtp_security or "starttls"
    user, password = row.smtp_username or "", ""
    if row.smtp_password_enc is not None:
        opened = open_smtp_password(settings.secret_key, row.smtp_password_enc)
        if opened is None:
            # Mật khẩu không giải mã được (SECRET_KEY đã đổi): gửi KHÔNG đăng nhập (bỏ user = không AUTH với mật khẩu
            # rỗng) — lỗi vào log như mọi lỗi SMTP; admin thấy "unreadable" ở Cài đặt › Hệ thống và nhập lại.
            user = ""
        else:
            password = opened
    return SmtpMailer(row.smtp_host, row.smtp_port or default_smtp_port(security), user, password, row.smtp_from or "",
                      security)


def resolve_mail(db: Session, settings: Settings, injected: Mailer | None) -> MailSetup:
    row = instance_row(db)
    if row.smtp_host:
        source, mailer = "settings", _from_row(settings, row)
    elif settings.smtp_host:
        source, mailer = "env", mailer_from_settings(settings)
    elif settings.mail_dev_log:
        source, mailer = "dev_log", LogMailer()
    else:
        source, mailer = "none", LogMailer()
    url = site_url(db, settings)[0]
    if injected is not None:
        # Test: mọi thư vào mailer tiêm; dòng nguồn vẫn nói đúng DB/env, còn "không có gì" thì tính như dev_log.
        return MailSetup(injected, source if source != "none" else "dev_log", url)
    return MailSetup(mailer, source, url)


def mail_enabled(db: Session, settings: Settings, injected: Mailer | None) -> bool:
    return resolve_mail(db, settings, injected).enabled


def deliver_later(app: FastAPI, mail: Mail) -> None:
    """BackgroundTask: giải cấu hình ngay lúc gửi rồi `deliver`. Mọi lỗi (đọc DB lẫn SMTP) chỉ thành một dòng log."""
    try:
        with app.state.session_factory() as db:
            setup = resolve_mail(db, app.state.settings, app.state.injected_mailer)
    except Exception:  # noqa: BLE001
        log.exception("Không đọc được cấu hình thư để gửi tới %s", mail.to)
        return
    deliver(setup.mailer, mail)
