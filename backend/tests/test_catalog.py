from app.providers.catalog import (
    DEFAULT_GEMINI_MODEL, ENGINE_BY_ID, ENGINES, EXCLUDED_MODEL_WORDS, GEMINI_MODELS, engine_items, model_choices,
)


def test_engine_catalog_matches_the_spec():
    assert [(e.id, e.mode, e.provider) for e in ENGINES] == [
        ("google_free", "plain", None), ("google_cloud", "plain", "google_cloud"), ("gemini", "ai", "gemini"),
    ]
    assert ENGINE_BY_ID["gemini"].label == "Gemini (Google AI Studio)"
    assert [model for model, _ in GEMINI_MODELS] == [
        "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-pro-preview",
    ]
    assert DEFAULT_GEMINI_MODEL == "gemini-3.5-flash-lite"


def test_engine_items_with_and_without_availability():
    plain = engine_items(None)
    assert plain[1] == {"id": "google_cloud", "mode": "plain", "label": "Google Cloud Translation", "needs_key": True}
    rich = engine_items({"gemini": True, "google_cloud": False})
    assert [(e["id"], e["available"]) for e in rich] == [("google_free", True), ("google_cloud", False), ("gemini", True)]


def test_model_choices_put_known_usable_models_first_then_the_rest():
    assert [m["id"] for m in model_choices(None)] == [model for model, _ in GEMINI_MODELS]
    key_models = [
        {"id": "gemini-4-exp", "label": "Gemini 4 Experimental"},
        {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
        {"id": "gemini-3.5-flash-lite", "label": "Flash-Lite"},
    ]
    choices = model_choices(key_models)
    assert [m["id"] for m in choices] == ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-exp"]
    assert choices[0]["label"] == "Gemini 3.5 Flash-Lite — rẻ, nhanh (khuyến nghị)"
    assert choices[2]["label"] == "Gemini 4 Experimental"


def test_models_that_cannot_translate_text_are_excluded():
    for word in ("tts", "live", "image", "embedding", "audio", "computer-use", "robotics"):
        assert word in EXCLUDED_MODEL_WORDS
