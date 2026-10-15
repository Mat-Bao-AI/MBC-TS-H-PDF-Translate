"""Hồ sơ dịch của một người dùng (spec 2026-10-14 §2, §7; 2026-10-15 §5): CRUD, giới hạn 20, mẫu, hồ sơ mặc định, kiểm văn bản tự do.

Mẫu có hai đời sống: người CHƯA bật Chế độ nâng cao thấy 5 mẫu trong code (`preset:<slug>`, chỉ đọc); lần đầu bật, `seed_presets`
chép chúng thành 5 dòng của chính người đó (`preset_slug`), từ đó danh sách chỉ còn dòng của user và mọi tham chiếu `preset:<slug>`
(snapshot cũ, request cũ, default_profile cũ) ánh xạ sang dòng có `preset_slug` tương ứng — một luật, một hàm: `resolve_ref`."""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.account import CONTROL_CATEGORIES
from ..db import iso, utcnow
from ..errors import ApiError
from ..models import TranslationProfile, User
from .presets import (
    CUSTOM_MAX, ENUM_FIELDS, NAME_MAX, PRESET_PREFIX, PRESETS, PROFILE_LIMIT, STYLE_DEFAULTS, STYLE_FIELDS, STYLE_OPTIONS, find_preset,
    preset_items,
)

log = logging.getLogger("profiles")
_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")  # ≥ 2 dòng trống liên tiếp → một dòng trống


def clean_text(raw: object, limit: int, *, code: str, field: str) -> str:
    """Văn bản tự do (yêu cầu riêng, ngữ cảnh): NFC, \\r\\n → \\n, gộp mỗi chuỗi ≥ 2 dòng trống liên tiếp thành một dòng trống, bỏ
    khoảng trắng hai đầu; cho phép \\n/\\t, từ chối ký tự khác thuộc CONTROL_CATEGORIES; độ dài tính SAU chuẩn hoá. None = rỗng.
    Sai → 422 `code` kèm `field`."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ApiError(422, code, field=field)
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_LINES.sub("\n\n", text).strip()
    if len(text) > limit or any(ch not in "\n\t" and unicodedata.category(ch) in CONTROL_CATEGORIES for ch in text):
        raise ApiError(422, code, field=field)
    return text


def clean_enum(raw: object, field: str, *, code: str) -> str:
    if not isinstance(raw, str) or raw not in STYLE_OPTIONS[field]:
        raise ApiError(422, code, field=field)
    return raw


def clean_profile_body(body: dict) -> dict:
    """Thân POST/PUT /api/profiles → name + 9 trường đã kiểm (422 invalid_profile field=…); trường enum bỏ qua = mặc định."""
    unknown = sorted(set(body) - {"name", *STYLE_FIELDS})
    if unknown:
        raise ApiError(422, "invalid_profile", field=unknown[0])
    name = unicodedata.normalize("NFC", body.get("name") if isinstance(body.get("name"), str) else "").strip()
    if not 1 <= len(name) <= NAME_MAX or any(unicodedata.category(ch) in CONTROL_CATEGORIES for ch in name):
        raise ApiError(422, "invalid_profile", field="name")
    values: dict = {"name": name}
    for field in ENUM_FIELDS:
        values[field] = clean_enum(body.get(field, STYLE_DEFAULTS[field]), field, code="invalid_profile")
    values["custom_instructions"] = clean_text(body.get("custom_instructions", ""), CUSTOM_MAX, code="invalid_profile",
                                               field="custom_instructions")
    return values


def profile_item(row: TranslationProfile) -> dict:
    return {"id": row.id, "kind": "custom", "name": row.name, **{field: getattr(row, field) for field in STYLE_FIELDS},
            "preset_slug": row.preset_slug, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


def _rows(db: Session, user: User) -> list[TranslationProfile]:
    return list(db.scalars(select(TranslationProfile).where(TranslationProfile.user_id == user.id)
                           .order_by(TranslationProfile.created_at, TranslationProfile.id)).all())


def _count(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(TranslationProfile).where(TranslationProfile.user_id == user.id)) or 0


def list_profiles(db: Session, user: User) -> list[dict]:
    """Đã gieo → chỉ dòng của user (5 mẫu đã là hồ sơ riêng, UI gắn "Từ mẫu" theo preset_slug); chưa gieo → mẫu trong code trước
    (thứ tự code), dòng riêng sau (thứ tự tạo)."""
    items = [profile_item(row) for row in _rows(db, user)]
    return items if user.profiles_seeded else [*preset_items(), *items]


def resolve_ref(db: Session, user: User, ref: object) -> TranslationProfile | dict | None:
    """MỘT luật ánh xạ tham chiếu hồ sơ (spec 2026-10-15 §5): id dòng của chính user → dòng; "preset:<slug>" → người đã gieo: dòng có
    preset_slug = slug của user (đã xoá → None); chưa gieo: mẫu trong code (dict, chỉ đọc). Không phải chuỗi / lạ / của người khác → None."""
    if not ref or not isinstance(ref, str):
        return None
    if ref.startswith(PRESET_PREFIX):
        if not user.profiles_seeded:
            return find_preset(ref)
        return db.scalar(select(TranslationProfile).where(TranslationProfile.user_id == user.id,
                                                          TranslationProfile.preset_slug == ref[len(PRESET_PREFIX):]))
    row = db.get(TranslationProfile, ref)
    return None if row is None or row.user_id != user.id else row


def _ref_id(found: TranslationProfile | dict) -> str:
    return found["id"] if isinstance(found, dict) else found.id


def find_profile(db: Session, user: User, ref: str | None) -> dict | None:
    """Item (cùng dáng với list_profiles) của tham chiếu, None khi không có — profiles.snapshot dùng."""
    found = resolve_ref(db, user, ref)
    return None if found is None else (found if isinstance(found, dict) else profile_item(found))


def _own_row(db: Session, user: User, profile_id: str) -> TranslationProfile:
    found = resolve_ref(db, user, profile_id)
    if isinstance(found, dict):
        raise ApiError(409, "preset_readonly")  # mẫu trong code (người chưa gieo): Nhân bản để sửa
    if found is None:
        raise ApiError(404, "profile_not_found")  # 404 cả với hồ sơ của người khác / mẫu đã xoá: không lộ là có tồn tại
    return found


def create_profile(db: Session, user: User, body: dict) -> dict:
    values = clean_profile_body(body)
    if _count(db, user) >= PROFILE_LIMIT:
        raise ApiError(409, "too_many_profiles", limit=PROFILE_LIMIT)
    now = utcnow()
    row = TranslationProfile(id=uuid.uuid4().hex[:12], user_id=user.id, created_at=now, updated_at=now, **values)
    db.add(row)
    db.commit()
    return profile_item(row)


def update_profile(db: Session, user: User, profile_id: str, body: dict) -> dict:
    row = _own_row(db, user, profile_id)
    for field, value in clean_profile_body(body).items():
        setattr(row, field, value)
    row.updated_at = utcnow()
    db.commit()
    return profile_item(row)


def delete_profile(db: Session, user: User, profile_id: str) -> None:
    row = _own_row(db, user, profile_id)
    if user.default_profile == row.id:
        user.default_profile = None  # cùng giao dịch với DELETE (spec §2)
    db.delete(row)
    db.commit()


def check_default_profile(db: Session, user: User, ref: object) -> str | None:
    """Giá trị hợp lệ cho users.default_profile: None, hoặc tham chiếu tới hồ sơ còn tồn tại; sai → 400 profile_not_found.
    Người đã gieo gửi "preset:<slug>" → lưu id dòng (chuẩn hoá); người chưa gieo → giữ "preset:<slug>" (seed_presets đổi sau)."""
    if ref is None:
        return None
    found = resolve_ref(db, user, ref)
    if found is None:
        raise ApiError(400, "profile_not_found")
    return _ref_id(found)


def effective_default_profile(db: Session, user: User) -> str | None:
    """default_profile để trả về: tham chiếu treo (hồ sơ đã mất) đọc như NULL (spec §2); preset: của người đã gieo → id dòng."""
    found = resolve_ref(db, user, user.default_profile)
    return None if found is None else _ref_id(found)


def _point_default_at_rows(user: User, ids: dict[str, str]) -> None:
    """default_profile còn là chuỗi thô "preset:<slug>" → id dòng gieo của slug (không có dòng → giữ nguyên, đọc như NULL). Sau đó
    xoá dòng thì xoá luôn mặc định (delete_profile so id), khôi phục lại không dựng lại mặc định đã bỏ."""
    if isinstance(user.default_profile, str) and user.default_profile.startswith(PRESET_PREFIX):
        user.default_profile = ids.get(user.default_profile[len(PRESET_PREFIX):], user.default_profile)


def seed_presets(db: Session, user: User) -> bool:
    """Lần đầu bật Chế độ nâng cao (spec 2026-10-15 §5): chép 5 mẫu thành hồ sơ riêng của user (preset_slug = slug) theo thứ tự PRESETS,
    created_at cách nhau 1 µs để danh sách giữ thứ tự mẫu, DỪNG khi chạm PROFILE_LIMIT (mẫu thiếu tạo lại bằng restore_presets khi có
    chỗ); default_profile "preset:<slug>" → id dòng mới. Idempotent và an toàn khi hai request song song: cờ users.profiles_seeded đặt
    bằng UPDATE có điều kiện TRƯỚC khi chèn, cùng giao dịch. Trả True khi lượt này gieo. Người gọi không được có thay đổi chưa commit
    (cả hai nhánh đều kết thúc giao dịch)."""
    claimed = db.execute(update(User).where(User.id == user.id, User.profiles_seeded.is_(False)).values(profiles_seeded=True)).rowcount
    if not claimed:
        db.rollback()  # request khác vừa gieo: nhả khoá ghi của UPDATE trượt ngay; user hết hạn → cờ/default_profile của bên thắng nạp lại
        return False
    count = _count(db, user)
    now = utcnow()
    created: dict[str, str] = {}
    for index, (slug, preset) in enumerate(PRESETS.items()):
        if count + len(created) >= PROFILE_LIMIT:
            break
        row = TranslationProfile(id=uuid.uuid4().hex[:12], user_id=user.id, preset_slug=slug, created_at=now + timedelta(microseconds=index),
                                 updated_at=now, **{field: preset[field] for field in ("name", *STYLE_FIELDS)})
        db.add(row)
        created[slug] = row.id
    _point_default_at_rows(user, created)
    user.profiles_seeded = True
    db.commit()
    return True


def ensure_seeded(db: Session, user: User) -> None:
    """Gieo một lần cho người đang bật Chế độ nâng cao mà chưa có dòng gieo (người dùng đợt 1 — gọi ở GET /api/settings, GET
    /api/profiles và phản hồi của PUT preferences). Gieo hỏng (khoá DB, hết đĩa) → log + rollback, request vẫn trả danh sách như
    chưa gieo: một lượt đọc không được 500 vì tác dụng phụ."""
    if not user.advance_mode or user.profiles_seeded:
        return
    try:
        seed_presets(db, user)
    except Exception:  # noqa: BLE001 - tác dụng phụ không được làm hỏng request đọc
        log.exception("Không gieo được hồ sơ mẫu cho %s", user.id)
        db.rollback()


def restore_presets(db: Session, user: User) -> dict:
    """POST /api/profiles/restore-presets (spec 2026-10-15 §5): chưa gieo → gieo; đã gieo → dòng gieo còn → đưa tên + 9 trường về mẫu
    (giữ id, updated_at mới), dòng đã xoá → tạo lại. Kiểm chỗ trống TRƯỚC mọi ghi (cả nhánh chưa gieo: không gieo dở dang, không lật
    cờ): thiếu → 409 too_many_profiles, không đổi gì. Một lượt khôi phục khác vừa commit đúng mẫu ta định tạo → chỉ mục duy nhất
    (user_id, preset_slug) chặn dòng trùng → rollback và chạy lại MỘT lần: lượt hai thấy dòng đó và đặt lại nó (hỏng lần nữa → ném)."""
    try:
        return _restore_presets(db, user)
    except IntegrityError:
        db.rollback()
        return _restore_presets(db, user)


def _restore_presets(db: Session, user: User) -> dict:
    if not user.profiles_seeded:
        before = _count(db, user)
        if before + len(PRESETS) > PROFILE_LIMIT:
            raise ApiError(409, "too_many_profiles", limit=PROFILE_LIMIT)
        if seed_presets(db, user):
            return {"updated": 0, "created": _count(db, user) - before}
        # request khác vừa gieo (seed_presets đã rollback, user nạp lại): khôi phục như người đã gieo
    rows = {row.preset_slug: row for row in db.scalars(select(TranslationProfile).where(
        TranslationProfile.user_id == user.id, TranslationProfile.preset_slug.is_not(None))).all()}
    missing = [slug for slug in PRESETS if slug not in rows]
    if _count(db, user) + len(missing) > PROFILE_LIMIT:
        raise ApiError(409, "too_many_profiles", limit=PROFILE_LIMIT)
    now = utcnow()
    ids: dict[str, str] = {}
    for index, (slug, preset) in enumerate(PRESETS.items()):
        values = {field: preset[field] for field in ("name", *STYLE_FIELDS)}
        if slug in rows:
            for field, value in values.items():
                setattr(rows[slug], field, value)
            rows[slug].updated_at = now
            ids[slug] = rows[slug].id
        else:
            row = TranslationProfile(id=uuid.uuid4().hex[:12], user_id=user.id, preset_slug=slug,
                                     created_at=now + timedelta(microseconds=index), updated_at=now, **values)
            db.add(row)
            ids[slug] = row.id
    _point_default_at_rows(user, ids)  # như seed_presets: chuỗi "preset:<slug>" còn sót (gieo từng dừng ở giới hạn) → id dòng
    db.commit()
    return {"updated": len(rows), "created": len(missing)}
