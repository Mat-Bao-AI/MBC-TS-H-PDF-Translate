from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from ..config import SMTP_SECURITIES, Settings

log = logging.getLogger("mailer")


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class LogMailer:
    """Chưa cấu hình SMTP: in thư ra log để lấy link khi chạy dev/E2E."""

    def send(self, mail: Mail) -> None:
        log.warning("MAIL to=%s subject=%s\n%s", mail.to, mail.subject, mail.body)


@dataclass(frozen=True)
class SmtpMailer:
    host: str
    port: int
    user: str
    password: str = field(repr=False)  # repr/log của mailer không được lộ mật khẩu SMTP
    sender: str
    security: str = "starttls"  # starttls (STARTTLS sau khi kết nối) | ssl (TLS ngầm định, cổng 465) | none

    def send(self, mail: Mail) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message.set_content(mail.body)
        if self.security not in SMTP_SECURITIES:
            # Đóng an toàn: giá trị lạ không được rơi về SMTP thường rồi gửi mật khẩu không mã hoá.
            raise ValueError(f"SMTP security phải là starttls, ssl hoặc none, nhận được {self.security!r}")
        # Kiểm chứng chỉ + tên máy: không truyền context thì Python 3.12 bắt tay TLS KHÔNG kiểm gì → MITM đọc được mật khẩu.
        # (Máy chủ SMTP dùng chứng chỉ tự ký sẽ lỗi — chưa có tuỳ chọn bỏ qua.)
        context = ssl.create_default_context()
        if self.security == "ssl":
            connection = smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=context)
        else:
            connection = smtplib.SMTP(self.host, self.port, timeout=15)
        with connection as smtp:
            if self.security == "starttls":
                smtp.starttls(context=context)
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)


def mailer_from_settings(settings: Settings) -> Mailer:
    """Mailer theo env SMTP_* — một nguồn trong thứ tự DB → env → dev_log → log (xem app.system.mail)."""
    if not settings.smtp_host:
        return LogMailer()
    return SmtpMailer(
        settings.smtp_host, settings.smtp_port, settings.smtp_user,
        settings.smtp_password, settings.smtp_from, settings.smtp_security,
    )


def deliver(mailer: Mailer, mail: Mail) -> None:
    """SMTP hỏng thì ghi log và bỏ qua — tài khoản vẫn tạo, người dùng bấm gửi lại sau."""
    try:
        mailer.send(mail)
    except Exception:  # noqa: BLE001
        # host:port cho biết nguồn nào (DB / env) đã được dùng — KHÔNG BAO GIỜ in mật khẩu.
        server = f" qua {mailer.host}:{mailer.port}" if isinstance(mailer, SmtpMailer) else ""
        log.exception("Không gửi được thư tới %s%s", mail.to, server)
