"""Hồ sơ dịch (spec 2026-10-14 §2): 9 trường + 5 hồ sơ mẫu định nghĩa trong code — chỉ đọc, "Nhân bản" để sửa.

Không phụ thuộc tiếng Việt: số/ngày là "theo quy ước ngôn ngữ đích" (app có 36 ngôn ngữ). Nhãn tiếng Việt là nháp (BA duyệt);
custom_instructions của mẫu viết tiếng Việt vì văn bản tự do của người dùng cũng đi nguyên văn vào prompt (Gemini đọc được).
"""

from __future__ import annotations

STYLE_OPTIONS: dict[str, tuple[str, ...]] = {
    "fidelity": ("literal", "balanced", "natural"),
    "tone": ("friendly", "professional", "academic", "simple"),
    "audience": ("self", "student", "client", "expert"),
    "terms": ("keep", "translate_with_original", "translate"),
    "proper_names": ("keep", "localize"),
    "numbers": ("keep", "target_convention"),
    "dates": ("keep", "target_convention"),
    "abbreviations": ("keep", "expand"),
}
ENUM_FIELDS: tuple[str, ...] = tuple(STYLE_OPTIONS)
STYLE_FIELDS: tuple[str, ...] = (*ENUM_FIELDS, "custom_instructions")
STYLE_DEFAULTS: dict[str, str] = {
    "fidelity": "balanced", "tone": "professional", "audience": "self", "terms": "translate", "proper_names": "keep",
    "numbers": "target_convention", "dates": "target_convention", "abbreviations": "keep", "custom_instructions": "",
}
NAME_MAX, CUSTOM_MAX, CONTEXT_MAX, PROFILE_LIMIT = 60, 1000, 2000, 20
PRESET_PREFIX = "preset:"

PRESETS: dict[str, dict[str, str]] = {
    "quick": {"name": "Đọc nhanh, tự nhiên", "fidelity": "natural", "tone": "friendly", "audience": "self", "terms": "translate",
              "proper_names": "keep", "numbers": "target_convention", "dates": "target_convention", "abbreviations": "expand",
              "custom_instructions": ""},
    "client": {"name": "Chuyên nghiệp gửi khách hàng", "fidelity": "balanced", "tone": "professional", "audience": "client",
               "terms": "translate_with_original", "proper_names": "keep", "numbers": "target_convention",
               "dates": "target_convention", "abbreviations": "expand", "custom_instructions": ""},
    "technical": {"name": "Tài liệu kỹ thuật", "fidelity": "balanced", "tone": "professional", "audience": "expert", "terms": "keep",
                  "proper_names": "keep", "numbers": "keep", "dates": "keep", "abbreviations": "keep",
                  "custom_instructions": "Giữ nguyên tên thư viện, hàm, lệnh, tham số, tệp và mọi định danh trong mã."},
    "beginner": {"name": "Dễ hiểu cho người mới", "fidelity": "natural", "tone": "simple", "audience": "student",
                 "terms": "translate_with_original", "proper_names": "keep", "numbers": "target_convention",
                 "dates": "target_convention", "abbreviations": "expand", "custom_instructions": "Ưu tiên câu ngắn, từ thông dụng."},
    "academic": {"name": "Học thuật, sát nghĩa", "fidelity": "literal", "tone": "academic", "audience": "expert",
                 "terms": "translate_with_original", "proper_names": "keep", "numbers": "keep", "dates": "keep",
                 "abbreviations": "keep", "custom_instructions": ""},
}


def preset_id(slug: str) -> str:
    return PRESET_PREFIX + slug


def preset_items() -> list[dict]:
    """Cùng dáng với profile_item của hồ sơ riêng; thứ tự = thứ tự hiển thị."""
    return [{"id": preset_id(slug), "kind": "preset", "name": preset["name"], **{field: preset[field] for field in STYLE_FIELDS},
             "preset_slug": None, "created_at": None, "updated_at": None} for slug, preset in PRESETS.items()]


def find_preset(ref: str) -> dict | None:
    if not ref.startswith(PRESET_PREFIX) or ref[len(PRESET_PREFIX):] not in PRESETS:
        return None
    return next(item for item in preset_items() if item["id"] == ref)
