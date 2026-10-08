from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None]
    default_engine: Mapped[str] = mapped_column(String(20), default="google_free")  # id trong providers.catalog
    default_model: Mapped[str | None] = mapped_column(String(64))  # chỉ có nghĩa khi default_engine = gemini
    display_name: Mapped[str | None] = mapped_column(String(50))  # NULL = chưa đặt; UI lùi về phần trước @ của email
    default_font: Mapped[str] = mapped_column(String(8), default="auto")  # một id của app.engine.fonts.PROFILE_IDS
    smtp_notice_dismissed: Mapped[bool] = mapped_column(default=False, server_default="0")  # đóng biểu ngữ "chưa cấu hình SMTP" — nhớ theo tài khoản
    is_admin: Mapped[bool] = mapped_column(default=False)  # chỉ đổi qua migration 0005 / POST /api/setup — không có API cấp quyền
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # HMAC của token, không lưu token thật
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class EmailToken(Base):
    __tablename__ = "email_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "verify" | "reset" | "new_email" — kind mới phải ≤ 10 ký tự
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    # HMAC của nonce trong cookie verify_nonce của trình duyệt đã xin link: chỉ trình duyệt đó
    # được tự đăng nhập khi bấm link. NULL = không tự đăng nhập.
    nonce_hash: Mapped[str | None] = mapped_column(String(64))
    new_email: Mapped[str | None] = mapped_column(String(254))  # chỉ với kind="new_email": địa chỉ mới đã chuẩn hoá


class File(Base):
    __tablename__ = "files"
    __table_args__ = (Index("ix_files_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    search_name: Mapped[str] = mapped_column(String(255))  # NFC + casefold, chỉ để tìm
    language: Mapped[str] = mapped_column(String(8))
    engine: Mapped[str] = mapped_column(String(20), default="google_free")  # lưu lúc tạo; Dịch lại dùng lại
    model: Mapped[str | None] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(12), default="")  # split|translate|render|"" (google_free luôn "")
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued|running|done|error
    done_pages: Mapped[int] = mapped_column(default=0)
    total_pages: Mapped[int] = mapped_column(default=0)
    untranslated: Mapped[int] = mapped_column(default=0)
    message: Mapped[str] = mapped_column(String(1000), default="")
    output_name: Mapped[str | None] = mapped_column(String(255))
    font: Mapped[str] = mapped_column(String(8), default="auto")  # lựa chọn lúc tải lên / lần dựng lại xong gần nhất
    font_used: Mapped[str | None] = mapped_column(String(8))  # sans|serif thực dùng (dòng {"font"} của worker); NULL = chưa biết
    rebuild_font: Mapped[str | None] = mapped_column(String(8))  # khác NULL = đang dựng lại với font này
    rebuild_error: Mapped[str] = mapped_column(String(1000), default="")  # lý do lần dựng lại gần nhất thất bại
    # Khác NULL = đang dịch lại TỪ ĐẦU theo lựa chọn mới (spec 2026-10-05 §6); language/engine/model ở trên giữ bản cũ
    # tới khi xong. rebuild_font khác NULL mà ba cột này NULL = dựng lại font (0 lời gọi API).
    retranslate_language: Mapped[str | None] = mapped_column(String(8))
    retranslate_engine: Mapped[str | None] = mapped_column(String(20))
    retranslate_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_api_credentials_user_provider"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # google_cloud | gemini
    secret: Mapped[str] = mapped_column(Text)  # base64(nonce 12B ‖ AES-GCM ciphertext) — xem providers/crypto.py
    hint: Mapped[str] = mapped_column(String(8))  # 4 ký tự cuối của key, thứ duy nhất trả về trình duyệt
    models: Mapped[str] = mapped_column(Text, default="[]")  # JSON [{"id","label"}] — gemini; "[]" với google_cloud
    verified_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class InstanceSettings(Base):
    """Đúng một dòng (id=1, CHECK): cấu hình của cả instance — SMTP ghi đè env, công tắc đăng ký, hạn chờ (spec 2026-10-05 §7)."""

    __tablename__ = "instance_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_instance_settings_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    smtp_host: Mapped[str | None] = mapped_column(String(253))  # khác NULL = "có cấu hình SMTP trong DB"
    smtp_port: Mapped[int | None]
    smtp_security: Mapped[str | None] = mapped_column(String(8))  # starttls | ssl | none
    smtp_username: Mapped[str | None] = mapped_column(String(254))  # NULL/rỗng = không đăng nhập SMTP
    smtp_password_enc: Mapped[str | None] = mapped_column(Text)  # AES-GCM như api_credentials.secret — xem system/store.py
    smtp_from: Mapped[str | None] = mapped_column(String(254))
    registration_open: Mapped[bool] = mapped_column(default=True)
    max_pending_per_user: Mapped[int | None]  # NULL = theo env MAX_PENDING_PER_USER
    setup_completed_at: Mapped[datetime | None]
    # Địa chỉ trang ghi lúc /setup (system.setup), chỉ để dựng link trong thư; env APP_BASE_URL thắng (system.store.site_url).
    site_url: Mapped[str | None] = mapped_column(String(2048))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
