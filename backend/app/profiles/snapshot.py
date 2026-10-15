"""Ảnh chụp cấu hình nâng cao của một lượt dịch (spec 2026-10-14 §3): bản sao GIÁ TRỊ, không con trỏ — đổi/xoá hồ sơ sau đó
không làm đổi snapshot. Không chứa language/engine/model/font (cột). Khoá `glossary` để dành cho đợt 2."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import User
from ..providers.catalog import ENGINE_BY_ID
from .presets import CONTEXT_MAX, CUSTOM_MAX, ENUM_FIELDS, STYLE_FIELDS
from .service import clean_enum, clean_text, find_profile

SCHEMA = 1


def parse_style_form(raw: str | None) -> dict | None:
    """`style` của multipart là chuỗi JSON object; None/rỗng = không gửi; sai (kể cả lồng quá sâu → RecursionError) → 422
    invalid_style field=style."""
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, RecursionError):
        raise ApiError(422, "invalid_style", field="style") from None
    if not isinstance(parsed, dict):
        raise ApiError(422, "invalid_style", field="style")
    return parsed


def clean_style(style: object) -> dict:
    """Các trường ghi đè đã kiểm (chỉ những trường có mặt); khoá lạ / giá trị sai → 422 invalid_style field=…"""
    if style is None:
        return {}
    if not isinstance(style, dict):
        raise ApiError(422, "invalid_style", field="style")
    cleaned: dict = {}
    for field, value in style.items():
        if field in ENUM_FIELDS:
            cleaned[field] = clean_enum(value, field, code="invalid_style")
        elif field == "custom_instructions":
            cleaned[field] = clean_text(value, CUSTOM_MAX, code="invalid_style", field=field)
        else:
            raise ApiError(422, "invalid_style", field=str(field))
    return cleaned


def requires_ai(engine_id: str) -> bool:
    engine = ENGINE_BY_ID.get(engine_id)
    return engine is not None and engine.mode == "ai"


def build_snapshot(db: Session, user: User, engine_id: str, profile_ref: str | None, style: object,
                   context: str | None) -> dict | None:
    """Snapshot của lượt dịch, hoặc None khi không có chỉ dẫn nào (`style` rỗng `{}` coi như không gửi). Kiểm hết, không ghi gì:
    chế độ tắt → 400 advance_mode_off; động cơ không AI → 400 style_requires_ai; hồ sơ lạ → 400 profile_not_found; style/context
    sai → 422 invalid_style."""
    if not profile_ref and not style and not context:
        return None
    if not user.advance_mode:
        raise ApiError(400, "advance_mode_off")
    if not requires_ai(engine_id):
        raise ApiError(400, "style_requires_ai")
    profile = find_profile(db, user, profile_ref) if profile_ref else None
    if profile_ref and profile is None:
        raise ApiError(400, "profile_not_found")
    overrides = clean_style(style)
    document_context = clean_text(context, CONTEXT_MAX, code="invalid_style", field="context") or None
    if profile is not None:
        base = {field: profile[field] for field in STYLE_FIELDS}
        changed = sorted(field for field, value in overrides.items() if value != base[field])
        effective: dict | None = {**base, **overrides}
        profile_part: dict | None = {"id": profile["id"], "name": profile["name"], "kind": profile["kind"]}
    else:
        changed = sorted(overrides)
        effective = overrides or None
        profile_part = None
    if profile_part is None and effective is None and document_context is None:
        return None
    return {"schema": SCHEMA, "mode": "advanced", "profile": profile_part, "style": effective, "overrides": changed,
            "document_context": document_context}


def dump(snapshot: dict | None) -> str | None:
    return None if snapshot is None else json.dumps(snapshot, ensure_ascii=False)


def load(text: str | None) -> dict | None:
    """Cột config/retranslate_config → object; NULL / JSON hỏng → None (UI hiện "Cơ bản")."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
