"""Danh mục engine dịch và model Gemini — nguồn duy nhất cho backend lẫn /api/meta."""

from __future__ import annotations

from dataclasses import dataclass

PLAIN, AI = "plain", "ai"


@dataclass(frozen=True)
class Engine:
    id: str
    mode: str  # plain | ai
    label: str
    provider: str | None  # None = không cần key


ENGINES: tuple[Engine, ...] = (
    Engine("google_free", PLAIN, "Google miễn phí", None),
    Engine("google_cloud", PLAIN, "Google Cloud Translation", "google_cloud"),
    Engine("gemini", AI, "Gemini (Google AI Studio)", "gemini"),
)
ENGINE_BY_ID: dict[str, Engine] = {engine.id: engine for engine in ENGINES}
PROVIDERS: tuple[str, ...] = ("google_cloud", "gemini")
PROVIDER_LABELS: dict[str, str] = {engine.provider: engine.label for engine in ENGINES if engine.provider}

# Thứ tự = thứ tự hiển thị. Nhãn tiếng Việt là bản nháp, BA duyệt sau.
GEMINI_MODELS: list[tuple[str, str]] = [
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite — rẻ, nhanh (khuyến nghị)"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash — chất lượng cao hơn"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview) — văn bản khó, đắt"),
]
GEMINI_LABELS: dict[str, str] = dict(GEMINI_MODELS)
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
# Model giọng nói / ảnh / embedding / điều khiển máy tính / robot không dịch văn bản được — "Gemini 3.5 Live
# Translate" cũng nằm trong số bị loại.
EXCLUDED_MODEL_WORDS: tuple[str, ...] = ("tts", "live", "image", "embedding", "audio", "computer-use", "robotics")


def engine_items(available: dict[str, bool] | None) -> list[dict]:
    """Danh sách engine cho API. `available` = {provider: đã có key?}; None → bỏ khoá `available` (cho /api/meta)."""
    items = []
    for engine in ENGINES:
        item: dict = {"id": engine.id, "mode": engine.mode, "label": engine.label, "needs_key": engine.provider is not None}
        if available is not None:
            item["available"] = engine.provider is None or bool(available.get(engine.provider))
        items.append(item)
    return items


def model_choices(key_models: list[dict] | None) -> list[dict]:
    """Ô chọn model (§3): chưa có key → danh mục tĩnh; có key → model tĩnh mà key dùng được (nhãn tĩnh)
    trước, rồi các model khác key trả về (nhãn = displayName)."""
    if key_models is None:
        return [{"id": model, "label": label} for model, label in GEMINI_MODELS]
    usable = {str(item.get("id")): str(item.get("label") or item.get("id")) for item in key_models}
    choices = [{"id": model, "label": label} for model, label in GEMINI_MODELS if model in usable]
    known = {choice["id"] for choice in choices}
    choices.extend({"id": model, "label": label} for model, label in usable.items() if model not in known)
    return choices
