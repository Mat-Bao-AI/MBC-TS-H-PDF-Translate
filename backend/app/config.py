"""Đọc cấu hình từ biến môi trường, một lần, lúc khởi động."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

LOCAL_HOSTS = ("localhost", "127.0.0.1")
# font_worker.py bọc worker.py (không sửa) để áp hồ sơ font của bản dịch; WORKER_CMD vẫn ghi đè được (image :e2e).
DEFAULT_WORKER_CMD: tuple[str, ...] = (sys.executable, str(Path(__file__).parent / "engine" / "font_worker.py"))
DEFAULT_HANDOFF_WORKER_CMD: tuple[str, ...] = (
    sys.executable, str(Path(__file__).parent / "engine" / "handoff_worker.py"),
)


SMTP_SECURITIES: tuple[str, ...] = ("starttls", "ssl", "none")


class ConfigError(RuntimeError):
    pass


def normalize_base_url(raw: str) -> str:
    """Kiểm + chuẩn hoá địa chỉ trang dùng trong thư: env APP_BASE_URL lẫn địa chỉ ghi lúc /setup (system.setup)."""
    base_url = raw.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError("APP_BASE_URL phải là địa chỉ đầy đủ, ví dụ https://pdf.example.com")
    try:
        host = urlsplit(base_url).hostname
    except ValueError:  # "http://[::1" — IPv6 hỏng: urlsplit ném, không phải địa chỉ đầy đủ
        raise ConfigError("APP_BASE_URL phải là địa chỉ đầy đủ, ví dụ https://pdf.example.com") from None
    if base_url.startswith("http://") and host not in LOCAL_HOSTS:
        # Cookie phiên đặt Secure: trình duyệt bỏ nó trên http thường (trừ localhost) → đăng nhập
        # "thành công" rồi bị đá ra trang đăng nhập mãi, không có lỗi nào để lần.
        raise ConfigError("APP_BASE_URL phải dùng https:// (http:// chỉ cho localhost / 127.0.0.1)")
    return base_url


def default_smtp_port(security: str) -> int:
    """Cổng khi env/DB không đặt: 465 cho TLS ngầm định (ssl), 587 (submission) cho starttls / none."""
    return 465 if security == "ssl" else 587


@dataclass(frozen=True)
class Settings:
    # Bí mật repr=False: in/log Settings (traceback, debug) không lộ SECRET_KEY, SMTP_PASSWORD, SETUP_TOKEN.
    secret_key: str = field(repr=False)
    app_base_url: str | None  # None = chưa đặt APP_BASE_URL → địa chỉ ghi lúc /setup (system.store.site_url)
    data_dir: Path
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = ""
    smtp_security: str = "starttls"  # starttls | ssl | none
    max_upload_mb: int = 50
    max_concurrent_jobs: int = 1
    max_pending_per_user: int = 3
    job_stall_seconds: float = 8 * 60
    job_timeout_seconds: float = 180 * 60
    default_target_lang: str = "vi"
    worker_cmd: tuple[str, ...] = DEFAULT_WORKER_CMD
    handoff_worker_cmd: tuple[str, ...] = DEFAULT_HANDOFF_WORKER_CMD
    static_dir: Path | None = None
    source_url: str = ""
    setup_token: str = field(default="", repr=False)  # rỗng = wizard /setup mở như WordPress; đặt cho app công khai (spec 2026-10-05 §2)
    mail_dev_log: bool = False  # MAIL_DEV_LOG=1: LogMailer nhưng TÍNH LÀ đã cấu hình (E2E đọc link từ log)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"

    @property
    def users_dir(self) -> Path:
        return self.data_dir / "users"


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        raise ConfigError(f"{name} phải là số nguyên dương, nhận được {raw!r}") from None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    secret = env.get("SECRET_KEY", "").strip()
    if len(secret) < 32:
        raise ConfigError(
            "SECRET_KEY chưa đặt hoặc ngắn hơn 32 ký tự. "
            "Sinh bằng: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    # Tuỳ chọn: không đặt = địa chỉ ghi lúc chạy /setup (system.store.site_url); chỉ dùng dựng link trong thư.
    raw_base_url = env.get("APP_BASE_URL", "").strip()
    base_url = normalize_base_url(raw_base_url) if raw_base_url else None
    smtp_host = env.get("SMTP_HOST", "").strip()
    smtp_from = env.get("SMTP_FROM", "").strip()
    if smtp_host and not smtp_from:
        raise ConfigError("SMTP_FROM bắt buộc khi đã đặt SMTP_HOST")
    security = env.get("SMTP_SECURITY", "").strip().lower()
    if not security:
        # Biến cũ SMTP_STARTTLS=0 vẫn hiểu là "none" (không mã hoá); không đặt gì = STARTTLS như trước.
        security = "none" if env.get("SMTP_STARTTLS", "1").strip().lower() in ("0", "false", "no") else "starttls"
    if security not in SMTP_SECURITIES:
        raise ConfigError(f"SMTP_SECURITY phải là starttls, ssl hoặc none, nhận được {security!r}")
    worker = env.get("WORKER_CMD", "").strip()
    handoff = env.get("HANDOFF_WORKER_CMD", "").strip()
    static = env.get("STATIC_DIR", "").strip()
    source_url = env.get("SOURCE_URL", "").strip()
    if source_url and not source_url.startswith("https://"):
        raise ConfigError("SOURCE_URL phải là địa chỉ https:// tới kho mã nguồn")
    return Settings(
        secret_key=secret,
        app_base_url=base_url,
        data_dir=Path(env.get("DATA_DIR", "/data").strip() or "/data"),
        smtp_host=smtp_host,
        smtp_port=_int(env, "SMTP_PORT", default_smtp_port(security)),
        smtp_user=env.get("SMTP_USER", "").strip(),
        smtp_password=env.get("SMTP_PASSWORD", ""),
        smtp_from=smtp_from,
        smtp_security=security,
        max_upload_mb=_int(env, "MAX_UPLOAD_MB", 50),
        max_concurrent_jobs=_int(env, "MAX_CONCURRENT_JOBS", 1),
        max_pending_per_user=_int(env, "MAX_PENDING_PER_USER", 3),
        job_stall_seconds=_int(env, "JOB_STALL_MINUTES", 8) * 60,
        job_timeout_seconds=_int(env, "JOB_TIMEOUT_MINUTES", 180) * 60,
        default_target_lang=env.get("DEFAULT_TARGET_LANG", "vi").strip() or "vi",
        worker_cmd=tuple(shlex.split(worker)) if worker else DEFAULT_WORKER_CMD,
        handoff_worker_cmd=tuple(shlex.split(handoff)) if handoff else DEFAULT_HANDOFF_WORKER_CMD,
        static_dir=Path(static) if static else None,
        source_url=source_url,
        setup_token=env.get("SETUP_TOKEN", "").strip(),
        mail_dev_log=env.get("MAIL_DEV_LOG", "").strip().lower() in ("1", "true", "yes"),
    )
