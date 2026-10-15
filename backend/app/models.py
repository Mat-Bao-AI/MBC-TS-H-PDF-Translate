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
    advance_mode: Mapped[bool] = mapped_column(default=False, server_default="0")  # Chế độ nâng cao (spec 2026-10-14 §2), mỗi người tự bật
    default_profile: Mapped[str | None] = mapped_column(String(40))  # "preset:<slug>" | id hồ sơ riêng | NULL = không áp hồ sơ
    profiles_seeded: Mapped[bool] = mapped_column(default=False, server_default="0")  # 5 mẫu đã được chép thành hồ sơ riêng (spec 2026-10-15 §5)
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


class TranslationProfile(Base):
    """Hồ sơ dịch riêng của một người (spec 2026-10-14 §2). 5 mẫu: chưa bật Chế độ nâng cao → trong code (app.profiles.presets,
    chỉ đọc); lần đầu bật → chép thành 5 dòng ở đây với preset_slug (spec 2026-10-15 §5)."""

    __tablename__ = "translation_profiles"
    # Mỗi mẫu tối đa một dòng gieo cho mỗi người (hai lượt khôi phục song song không chèn trùng); preset_slug NULL không va nhau.
    __table_args__ = (Index("uq_translation_profiles_user_preset", "user_id", "preset_slug", unique=True),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    preset_slug: Mapped[str | None] = mapped_column(String(16))  # khác NULL = dòng gieo từ PRESETS[slug] ("Từ mẫu"); đổi tên/giá trị vẫn giữ
    fidelity: Mapped[str] = mapped_column(String(8))  # literal | balanced | natural
    tone: Mapped[str] = mapped_column(String(12))  # friendly | professional | academic | simple
    audience: Mapped[str] = mapped_column(String(8))  # self | student | client | expert
    terms: Mapped[str] = mapped_column(String(24))  # keep | translate_with_original | translate
    proper_names: Mapped[str] = mapped_column(String(8))  # keep | localize
    numbers: Mapped[str] = mapped_column(String(17))  # keep | target_convention
    dates: Mapped[str] = mapped_column(String(17))  # keep | target_convention
    abbreviations: Mapped[str] = mapped_column(String(6))  # keep | expand
    custom_instructions: Mapped[str] = mapped_column(Text, default="")  # ≤ 1000 ký tự, đi nguyên văn vào prompt
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


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
    # Ảnh chụp cấu hình nâng cao (JSON, spec 2026-10-14 §3) của bản dịch hiện tại; NULL = cơ bản. retranslate_config = của lượt
    # dịch lại đang chờ (đổi chỗ vào config khi xong, NULL khi lỗi — cùng khuôn retranslate_*).
    config: Mapped[str | None] = mapped_column(Text)
    retranslate_config: Mapped[str | None] = mapped_column(Text)
    version_no: Mapped[int] = mapped_column(default=1, server_default="1")  # số của bản hiện tại; +1 mỗi lần dịch lại tệp done xong
    # Khôi phục bản cũ (spec 2026-10-15 §2): restore_version khác NULL = đang khôi phục từ bản này — luôn đi CÙNG retranslate_* + rebuild_font
    # của bản nguồn (runner suy "đang thay bản" từ chúng như dịch lại). restored_from = bản hiện tại là bản sao của "Bản N"; NULL = dịch thật.
    restore_version: Mapped[str | None] = mapped_column(String(12))
    restored_from: Mapped[int | None]
    # Lúc bản dịch hiện tại hoàn tất (spec 2026-10-15 §4): đặt khi dịch / dịch lại / khôi phục xong; dựng lại font KHÔNG đổi; _claim_next
    # không xoá (khác finished_at). NULL với tệp chưa xong hoặc đang dựng lại font lúc nâng cấp — UI lùi về finished_at.
    translated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class FileVersion(Base):
    """Kho bản cũ (spec 2026-10-14 §5): mỗi dòng = một bản dịch đã bị thay; tệp ở <file_dir>/versions/<id>/<output_name>
    (+ segments.* nếu bản đó có bảng đoạn, spec 2026-10-15 §3). Bản hiện tại vẫn là dòng `files`. finished_at luôn NULL (runner
    xoá giờ xong khi nhận job) — giờ dịch là translated_at (NULL với bản cất trước 1b → UI dùng archived_at)."""

    __tablename__ = "file_versions"
    __table_args__ = (Index("ix_file_versions_file_version", "file_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    version_no: Mapped[int]
    language: Mapped[str] = mapped_column(String(8))
    engine: Mapped[str] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(64))
    font: Mapped[str] = mapped_column(String(8))
    font_used: Mapped[str | None] = mapped_column(String(8))
    config: Mapped[str | None] = mapped_column(Text)
    output_name: Mapped[str] = mapped_column(String(255))
    untranslated: Mapped[int] = mapped_column(default=0)
    finished_at: Mapped[datetime | None]
    archived_at: Mapped[datetime] = mapped_column(default=utcnow)
    restored_from: Mapped[int | None]  # bản này từng là bản sao của "Bản N" (chép từ files.restored_from lúc cất)
    translated_at: Mapped[datetime | None]  # chép từ files.translated_at lúc cất; bản cất trước 1b → NULL (UI lùi về archived_at)


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
    max_versions: Mapped[int | None]  # NULL = DEFAULT_MAX_VERSIONS (3); tính cả bản hiện tại (spec 2026-10-14 §5)
    setup_completed_at: Mapped[datetime | None]
    # Địa chỉ trang ghi lúc /setup (system.setup), chỉ để dựng link trong thư; env APP_BASE_URL thắng (system.store.site_url).
    site_url: Mapped[str | None] = mapped_column(String(2048))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
