from dataclasses import replace

import pytest
from sqlalchemy import func, select

from app.models import ApiCredential
from app.providers import credentials
from helpers import GEMINI_MODELS_BODY, GOOGLE_ERRORS, FakeTransport, cloud_reply, save_key

KEY = "AIza-test-key-0001"
LITE = "gemini-3.5-flash-lite"


@pytest.fixture
def me(sign_up) -> dict:
    return sign_up("an@example.com")


def use_transport(client, *replies, handler=None) -> FakeTransport:
    transport = FakeTransport(*replies, handler=handler)
    client.app.state.provider_transport = transport
    return transport


def put_key(client, provider="gemini", key=KEY):
    return client.put(f"/api/settings/credentials/{provider}", json={"api_key": key})


def engine(body, engine_id) -> dict:
    return next(item for item in body["engines"] if item["id"] == engine_id)


def credential_rows(client) -> int:
    with client.app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(ApiCredential)) or 0


def test_settings_default_without_keys(client, me):
    body = client.get("/api/settings").json()
    assert body["default_engine"] == "google_free" and body["default_model"] is None
    assert [(e["id"], e["mode"], e["needs_key"], e["available"]) for e in body["engines"]] == [
        ("google_free", "plain", False, True), ("google_cloud", "plain", True, False), ("gemini", "ai", True, False),
    ]
    assert body["gemini_models"][0] == {"id": LITE, "label": "Gemini 3.5 Flash-Lite — rẻ, nhanh (khuyến nghị)"}
    assert len(body["gemini_models"]) == 4 and body["credentials"] == []
    assert (body["advance_mode"], body["default_profile"], body["profile_limit"]) == (False, None, 20)
    assert [item["kind"] for item in body["profiles"]] == ["preset"] * 5


def test_settings_require_login(client):
    assert client.get("/api/settings").status_code == 401
    assert put_key(client).status_code == 401
    assert client.put("/api/settings/preferences", json={"default_engine": "google_free"}).status_code == 401
    assert client.delete("/api/settings/credentials/gemini").status_code == 401


def test_saving_a_gemini_key_verifies_stores_models_and_switches_the_default(client, me):
    transport = use_transport(client, (200, GEMINI_MODELS_BODY))
    response = put_key(client)
    assert response.status_code == 200, response.text
    assert transport.calls[0]["headers"]["x-goog-api-key"] == KEY
    body = response.json()
    assert body["default_engine"] == "gemini" and body["default_model"] == LITE
    [credential] = body["credentials"]
    assert credential["provider"] == "gemini" and credential["hint"] == "0001" and credential["verified_at"].endswith("Z")
    assert [m["id"] for m in credential["models"]] == ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-exp"]
    # Ô chọn model: model tĩnh mà key dùng được (nhãn tĩnh) trước, rồi model lạ (nhãn displayName).
    assert [m["id"] for m in body["gemini_models"]] == ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-exp"]
    assert body["gemini_models"][2]["label"] == "Gemini 4 Experimental"
    assert engine(body, "gemini")["available"] is True and engine(body, "google_cloud")["available"] is False


def test_the_key_itself_never_comes_back(client, me):
    use_transport(client, (200, GEMINI_MODELS_BODY))
    assert KEY not in put_key(client).text
    assert KEY not in client.get("/api/settings").text
    with client.app.state.session_factory() as db:
        [row] = db.scalars(select(ApiCredential)).all()
        assert KEY not in row.secret and row.hint == "0001"


def test_invalid_key_is_not_saved(client, me):
    use_transport(client, (401, {"error": {"message": "API key not valid"}}))
    response = put_key(client)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "invalid_api_key"}}
    assert client.get("/api/settings").json()["credentials"] == [] and credential_rows(client) == 0


def test_provider_outage_is_not_saved(client, me):
    use_transport(client, (503, {}))
    response = put_key(client)
    assert response.status_code == 502 and response.json() == {"detail": {"code": "provider_unavailable"}}
    assert credential_rows(client) == 0


@pytest.mark.parametrize(("provider", "name", "status", "code"), [
    ("gemini", "gemini_key_invalid", 400, "invalid_api_key"),
    ("google_cloud", "cloud_key_invalid", 400, "invalid_api_key"),
    ("gemini", "gemini_service_disabled", 400, "api_not_enabled"),
    ("google_cloud", "cloud_access_not_configured", 400, "api_not_enabled"),
    ("google_cloud", "cloud_billing_disabled", 400, "billing_disabled"),
    ("google_cloud", "cloud_service_blocked", 400, "key_restricted"),
    ("gemini", "gemini_referrer_blocked", 400, "key_restricted"),
    ("gemini", "gemini_location", 400, "provider_rejected"),
    ("gemini", "gemini_overloaded", 502, "provider_unavailable"),
    ("google_cloud", "internal", 502, "provider_unavailable"),
    ("gemini", "gemini_per_minute", 502, "provider_unavailable"),
])
def test_key_check_failures_report_the_real_cause_and_save_nothing(client, me, provider, name, status, code):
    """Không phải mọi 400/401/403 đều là "key sai": API chưa bật, chưa bật thanh toán, key bị giới hạn…
    mỗi thứ một mã để người dùng sửa đúng chỗ."""
    use_transport(client, GOOGLE_ERRORS[name])
    response = put_key(client, provider)
    assert response.status_code == status and response.json() == {"detail": {"code": code}}
    assert credential_rows(client) == 0
    assert client.get("/api/settings").json()["default_engine"] == "google_free"


def test_key_check_failure_logs_a_diagnostic_without_the_key(client, me, caplog):
    use_transport(client, GOOGLE_ERRORS["gemini_service_disabled"])
    with caplog.at_level("INFO"):
        assert put_key(client).status_code == 400
    assert "provider=gemini http=403 status=PERMISSION_DENIED reason=SERVICE_DISABLED" in caplog.text
    assert KEY not in caplog.text and "project" not in caplog.text


@pytest.mark.parametrize("key", [
    "ngan", "co khoang trang o giua", "x" * 201,
    "​AIza-test-key-0001",  # zero-width space ở đầu — isspace() không bắt được, isascii() thì có
    "AIza-test-key-0001﻿",  # BOM ở cuối — cùng lý do
    "AIza-tạst-key-0001",  # "ạ" — ngoài Latin-1/ASCII, httpx/requests không encode được header latin-1
])
def test_malformed_keys_are_refused_before_calling_the_provider(client, me, key):
    transport = use_transport(client)
    response = put_key(client, key=key)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "invalid_api_key"}}
    assert transport.calls == []


def test_surrounding_whitespace_is_trimmed(client, me):
    transport = use_transport(client, (200, cloud_reply(["ok"])))
    assert put_key(client, "google_cloud", f"  {KEY}\n").status_code == 200
    assert transport.calls[0]["headers"]["X-Goog-Api-Key"] == KEY
    assert client.get("/api/settings").json()["credentials"][0]["hint"] == "0001"


def test_replacing_a_key_keeps_one_row_and_updates_the_hint(client, me):
    use_transport(client, (200, GEMINI_MODELS_BODY), (200, GEMINI_MODELS_BODY))
    put_key(client)
    assert client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": "gemini-3.8-flash"}).status_code == 200
    response = put_key(client, key="AIza-another-key-9999")
    assert response.status_code == 200
    [credential] = response.json()["credentials"]
    assert credential["hint"] == "9999" and credential_rows(client) == 1
    assert response.json()["default_model"] == "gemini-3.8-flash"  # thay key không đụng mặc định đã chọn


def test_gemini_first_time_does_not_override_a_chosen_cloud_default(client, me):
    use_transport(client, (200, cloud_reply(["ok"])), (200, GEMINI_MODELS_BODY))
    put_key(client, "google_cloud")
    assert client.put("/api/settings/preferences", json={"default_engine": "google_cloud"}).status_code == 200
    body = put_key(client).json()
    assert body["default_engine"] == "google_cloud" and body["default_model"] is None


def test_deleting_a_key_falls_back_to_google_free(client, me):
    save_key(client, "gemini")
    assert client.delete("/api/settings/credentials/gemini").status_code == 204
    body = client.get("/api/settings").json()
    assert body["default_engine"] == "google_free" and body["default_model"] is None and body["credentials"] == []
    assert engine(body, "gemini")["available"] is False and credential_rows(client) == 0
    assert client.delete("/api/settings/credentials/gemini").status_code == 204  # xoá lần nữa vẫn 204


def test_preferences_are_validated(client, me):
    missing = client.put("/api/settings/preferences", json={"default_engine": "gemini"})
    assert missing.status_code == 400 and missing.json() == {"detail": {"code": "missing_api_key"}}
    unknown = client.put("/api/settings/preferences", json={"default_engine": "deepl"})
    assert unknown.status_code == 400 and unknown.json() == {"detail": {"code": "unsupported_engine"}}
    save_key(client, "gemini")
    bad = client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": "gemini-3.1-pro-preview"})
    assert bad.status_code == 400 and bad.json() == {"detail": {"code": "unsupported_model"}}  # key không dùng được model này
    good = client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": "gemini-3.8-flash"})
    assert good.status_code == 200 and good.json()["default_model"] == "gemini-3.8-flash"
    plain = client.put("/api/settings/preferences", json={"default_engine": "google_free", "default_model": "gemini-3.8-flash"})
    assert plain.status_code == 200 and plain.json()["default_model"] is None  # model chỉ có nghĩa với gemini
    assert client.get("/api/settings").json()["default_engine"] == "google_free"


def test_default_font_starts_at_auto_and_can_be_saved(client, me):
    assert client.get("/api/settings").json()["default_font"] == "auto"
    response = client.put("/api/settings/preferences", json={"default_engine": "google_free", "default_font": "serif"})
    assert response.status_code == 200 and response.json()["default_font"] == "serif"
    assert client.get("/api/settings").json()["default_font"] == "serif"


def test_preferences_without_a_font_keep_the_saved_one(client, me):
    client.put("/api/settings/preferences", json={"default_engine": "google_free", "default_font": "sans"})
    response = client.put("/api/settings/preferences", json={"default_engine": "google_free"})
    assert response.status_code == 200 and response.json()["default_font"] == "sans"


@pytest.mark.parametrize("font", ["", "comic", "SANS", "Liberation Sans"])
def test_unknown_font_is_refused_and_nothing_changes(client, me, font):
    response = client.put("/api/settings/preferences", json={"default_engine": "google_free", "default_font": font})
    assert response.status_code == 400 and response.json() == {"detail": {"code": "unsupported_font"}}
    assert client.get("/api/settings").json()["default_font"] == "auto"


def test_unknown_provider_is_404(client, me):
    assert put_key(client, "deepl").status_code == 404
    assert client.delete("/api/settings/credentials/deepl").status_code == 404


def test_keys_are_private_to_their_owner(client, sign_up):
    sign_up("an@example.com")
    save_key(client, "gemini")
    sign_up("binh@example.com")
    body = client.get("/api/settings").json()
    assert body["credentials"] == [] and body["default_engine"] == "google_free"
    assert engine(body, "gemini")["available"] is False


def test_rotated_secret_key_means_no_key(client, me):
    save_key(client, "gemini")
    client.app.state.settings = replace(client.app.state.settings, secret_key="t" * 32)
    body = client.get("/api/settings").json()
    assert body["credentials"] == [] and engine(body, "gemini")["available"] is False
    assert body["default_engine"] == "gemini"  # mặc định vẫn ghi gemini; frontend tự lùi về Dịch thuần (Task 8)
    missing = client.put("/api/settings/preferences", json={"default_engine": "gemini"})
    assert missing.status_code == 400 and missing.json() == {"detail": {"code": "missing_api_key"}}


def test_gemini_key_with_no_usable_models_is_rejected(client, me):
    """Quyết định của controller (ghi đè brief): key verify OK nhưng danh sách model dùng được rỗng
    (toàn model bị loại bởi EXCLUDED_MODEL_WORDS hoặc không hỗ trợ generateContent) → 400
    no_usable_models, KHÔNG lưu gì, không đụng default_engine/default_model."""
    body = {"models": [
        {"name": "models/gemini-3.5-flash-tts", "displayName": "TTS", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-embedding-001", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
    ]}
    use_transport(client, (200, body))
    response = put_key(client)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "no_usable_models"}}
    settings = client.get("/api/settings").json()
    assert settings["credentials"] == [] and credential_rows(client) == 0
    assert settings["default_engine"] == "google_free" and settings["default_model"] is None


def test_rotating_the_secret_then_resaving_the_key_counts_as_first_time(client, me):
    """Fix round 1 (1/3): dòng cũ không giải mã được nữa (đổi SECRET_KEY) đã bị ẩn khỏi /api/settings
    như chưa từng có key — lưu lại key phải được coi là lần đầu, kể cả việc tự chọn default_engine,
    chứ không phải vì `row is not None` (dòng vẫn còn trong DB, chỉ là không đọc được)."""
    save_key(client, "gemini")  # lần lưu thật sự đầu tiên: default_engine tự chuyển sang gemini
    assert client.put("/api/settings/preferences", json={"default_engine": "google_free"}).status_code == 200
    client.app.state.settings = replace(client.app.state.settings, secret_key="t" * 32)
    body = save_key(client, "gemini")  # lưu lại dưới secret mới: dòng cũ (secret cũ) coi như chưa có
    assert body["default_engine"] == "gemini" and body["default_model"] == LITE
    assert credential_rows(client) == 1  # vẫn một dòng duy nhất (ghi đè, không chèn thêm)


@pytest.mark.parametrize("corrupt", ["null", "42", '"abc"', "{}", "khong phai JSON"])
def test_corrupt_stored_models_never_crash_and_fall_back_to_unsupported_model(client, me, corrupt):
    """Fix round 1 (2/3): cột `models` hỏng (NULL/không phải list/JSON rác) — GET /api/settings
    phải trả [] thay vì 500 (TypeError khi json.loads lặp qua giá trị không phải list), và việc chọn
    model mặc định (không truyền model) phải trả 400 unsupported_model thay vì IndexError (500) khi
    danh sách model dùng được rỗng."""
    save_key(client, "gemini")
    with client.app.state.session_factory() as db:
        row = db.scalar(select(ApiCredential).where(ApiCredential.provider == "gemini"))
        row.models = corrupt
        db.commit()
    body = client.get("/api/settings").json()
    assert body["credentials"][0]["models"] == [] and body["gemini_models"] == []
    response = client.put("/api/settings/preferences", json={"default_engine": "gemini"})
    assert response.status_code == 400 and response.json() == {"detail": {"code": "unsupported_model"}}


def test_concurrent_first_save_recovers_from_the_unique_constraint_race(client, me, monkeypatch):
    """Fix round 1 (3/3): giả lập race trên UNIQUE(user_id, provider) — lookup đầu tiên (do một request
    khác vừa insert xong ngay trước ta) trả None dù dòng đã có thật trong DB; code phải rollback, đọc
    lại dòng thật rồi cập nhật nó, không được ném 500 vì IntegrityError."""
    save_key(client, "gemini")  # dòng thật đã tồn tại
    original = credentials._find_credential
    calls = {"n": 0}

    def flaky(db, user_id, provider):
        calls["n"] += 1
        return None if calls["n"] == 1 else original(db, user_id, provider)

    monkeypatch.setattr(credentials, "_find_credential", flaky)
    use_transport(client, (200, GEMINI_MODELS_BODY))
    response = put_key(client, key="AIza-another-key-9999")
    assert response.status_code == 200, response.text
    [credential] = response.json()["credentials"]
    assert credential["hint"] == "9999" and credential_rows(client) == 1  # ghi đè dòng thật, không chèn trùng
    assert calls["n"] == 2  # lookup đầu (giả) rồi lookup phục hồi sau rollback


# ---- Model Gemini bị Google gỡ (spec 2026-10-02 §3) ---------------------------------------------

def drop(client, user_id, model):
    with client.app.state.session_factory() as db:
        return credentials.drop_gemini_model(db, user_id, model)


def model_ids(body) -> list[str]:
    return [m["id"] for m in body["gemini_models"]]


def test_a_model_google_removed_is_dropped_and_the_default_moves_to_lite(client, me):
    save_key(client, "gemini")
    client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": "gemini-3.8-flash"})
    assert drop(client, me["id"], "gemini-3.8-flash") == "Gemini 3.5 Flash-Lite"
    body = client.get("/api/settings").json()
    assert model_ids(body) == ["gemini-3.5-flash-lite", "gemini-4-exp"]
    assert [m["id"] for m in body["credentials"][0]["models"]] == ["gemini-3.5-flash-lite", "gemini-4-exp"]
    assert (body["default_engine"], body["default_model"]) == ("gemini", LITE)


def test_dropping_the_default_lite_model_picks_the_first_remaining_one(client, me):
    save_key(client, "gemini")  # lần lưu đầu: mặc định thành gemini + Flash-Lite
    assert drop(client, me["id"], LITE) == "Gemini 3.8 Flash"
    body = client.get("/api/settings").json()
    assert (body["default_engine"], body["default_model"]) == ("gemini", "gemini-3.8-flash")


def test_dropping_the_last_model_falls_back_to_google_free(client, me):
    use_transport(client, (200, {"models": [GEMINI_MODELS_BODY["models"][0]]}))  # key chỉ có Flash-Lite
    assert put_key(client).status_code == 200
    assert drop(client, me["id"], LITE) == "Google miễn phí"
    body = client.get("/api/settings").json()
    assert (body["default_engine"], body["default_model"], body["gemini_models"]) == ("google_free", None, [])


def test_dropping_a_model_that_is_not_the_default_changes_nothing_else(client, me):
    save_key(client, "gemini")
    assert drop(client, me["id"], "gemini-4-exp") is None
    body = client.get("/api/settings").json()
    assert model_ids(body) == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert (body["default_engine"], body["default_model"]) == ("gemini", LITE)


def test_saving_the_key_again_brings_a_dropped_model_back(client, me):
    save_key(client, "gemini")
    drop(client, me["id"], "gemini-3.8-flash")
    assert "gemini-3.8-flash" in model_ids(save_key(client, "gemini"))


# --- giới hạn tốc độ lưu key: mỗi lần lưu là một request thật tới Google bằng key người dán ---

class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(client) -> FakeClock:
    from app.auth.ratelimit import SlidingWindow

    fake = FakeClock()
    client.app.state.credential_user_throttle = SlidingWindow(limit=10, window_seconds=900, clock=fake)
    client.app.state.credential_ip_throttle = SlidingWindow(limit=20, window_seconds=900, clock=fake)
    return fake


@pytest.fixture
def switch_to(client, sign_up):
    """Đăng ký nhiều tài khoản trên cùng client (cùng IP), nhớ cookie phiên của từng người."""
    import httpx

    jars: dict[str, httpx.Cookies] = {}

    def _switch(email: str) -> None:
        if email not in jars:
            sign_up(email)
            jars[email] = httpx.Cookies(client.cookies)
        client.cookies.clear()
        client.cookies.update(jars[email])

    return _switch


def test_user_is_capped_at_10_saves_per_window_without_calling_the_provider(client, me, clock):
    transport = use_transport(client, handler=lambda *_: (200, GEMINI_MODELS_BODY))
    for _ in range(10):
        assert put_key(client).status_code == 200
    calls = len(transport.calls)
    response = put_key(client)
    assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_requests"}}
    assert len(transport.calls) == calls


def test_another_user_on_the_same_ip_can_still_save(client, clock, switch_to):
    use_transport(client, handler=lambda *_: (200, GEMINI_MODELS_BODY))
    switch_to("one@example.com")
    for _ in range(10):
        assert put_key(client).status_code == 200
    assert put_key(client).status_code == 429
    switch_to("two@example.com")
    assert put_key(client).status_code == 200


def test_ip_is_capped_at_20_and_the_refused_user_gets_the_hit_back(client, clock, switch_to):
    use_transport(client, handler=lambda *_: (200, GEMINI_MODELS_BODY))
    for email, count in (("a@example.com", 8), ("b@example.com", 8), ("c@example.com", 4)):
        switch_to(email)
        for _ in range(count):
            assert put_key(client).status_code == 200
    switch_to("d@example.com")
    response = put_key(client)
    assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_requests"}}
    # Lượt của d bị IP từ chối nên đã được trả lại: d không bị trừ oan, hết cửa sổ IP là lưu được ngay.
    # Mở lại hạn mức IP: d còn đủ cả 10 lượt của riêng mình (lượt bị từ chối không bị tính).
    client.app.state.credential_ip_throttle.reset("testclient")
    for _ in range(10):
        assert put_key(client).status_code == 200
    assert put_key(client).status_code == 429


def test_window_expires_after_900_seconds(client, me, clock):
    use_transport(client, handler=lambda *_: (200, GEMINI_MODELS_BODY))
    for _ in range(10):
        assert put_key(client).status_code == 200
    assert put_key(client).status_code == 429
    clock.now += 899
    assert put_key(client).status_code == 429
    clock.now += 2
    assert put_key(client).status_code == 200


def test_rejected_keys_and_unknown_providers_count_too(client, me, clock):
    use_transport(client, handler=lambda *_: GOOGLE_ERRORS["gemini_key_invalid"])
    for _ in range(9):
        assert put_key(client).status_code == 400
    assert put_key(client, provider="khong-co").status_code == 404
    assert put_key(client).status_code == 429


def test_get_and_delete_are_never_throttled(client, me, clock):
    use_transport(client, handler=lambda *_: (200, GEMINI_MODELS_BODY))
    for _ in range(10):
        assert put_key(client).status_code == 200
    assert put_key(client).status_code == 429
    assert client.get("/api/settings").status_code == 200
    assert client.put("/api/settings/preferences", json={"default_engine": "google_free"}).status_code == 200
    assert client.delete("/api/settings/credentials/gemini").status_code == 204
    assert client.delete("/api/settings/credentials/gemini").status_code == 204


# ---- Dịch thuần ⇒ tắt Chế độ nâng cao (spec 2026-10-15 §6) ------------------------------------------------------

SLUGS = ["quick", "client", "technical", "beginner", "academic"]


def test_a_plain_default_engine_turns_advanced_mode_off_whatever_the_body_says(client, me):
    body = client.put("/api/settings/preferences", json={"default_engine": "google_free", "advance_mode": True}).json()
    assert body["advance_mode"] is False and client.get("/api/auth/me").json()["advance_mode"] is False
    assert all(item["id"].startswith("preset:") for item in body["profiles"])  # không gieo
    save_key(client, "gemini")  # lần lưu đầu đổi mặc định sang Gemini — KHÔNG tự bật
    assert client.get("/api/settings").json()["advance_mode"] is False
    on = client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": LITE, "advance_mode": True,
                                                       "default_profile": "preset:quick"}).json()
    assert on["advance_mode"] is True and [item["preset_slug"] for item in on["profiles"]] == SLUGS
    quick = on["profiles"][0]["id"]
    assert on["default_profile"] == quick
    off = client.put("/api/settings/preferences", json={"default_engine": "google_free"}).json()  # không nhắc advance_mode
    assert (off["advance_mode"], off["default_profile"]) == (False, quick)  # tắt công tắc, không xoá gì
    assert len(off["profiles"]) == 5 and client.get("/api/auth/me").json()["advance_mode"] is False


def test_deleting_the_key_behind_the_default_engine_turns_advanced_mode_off_but_another_key_does_not(client, me):
    save_key(client, "gemini")
    on = client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": LITE, "advance_mode": True}).json()
    assert on["advance_mode"] is True
    save_key(client, "google_cloud")
    assert client.delete("/api/settings/credentials/google_cloud").status_code == 204
    assert client.get("/api/settings").json()["advance_mode"] is True  # mặc định vẫn là Gemini
    assert client.delete("/api/settings/credentials/gemini").status_code == 204
    body = client.get("/api/settings").json()
    assert (body["default_engine"], body["advance_mode"]) == ("google_free", False)
    assert [item["preset_slug"] for item in body["profiles"]] == SLUGS  # hồ sơ giữ nguyên
    assert client.get("/api/auth/me").json()["advance_mode"] is False


def test_dropping_the_last_gemini_model_turns_advanced_mode_off(client, me):
    use_transport(client, (200, {"models": [GEMINI_MODELS_BODY["models"][0]]}))  # key chỉ có Flash-Lite
    assert put_key(client).status_code == 200
    assert client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": LITE, "advance_mode": True}).json()["advance_mode"] is True
    assert drop(client, me["id"], LITE) == "Google miễn phí"
    body = client.get("/api/settings").json()
    assert (body["default_engine"], body["advance_mode"]) == ("google_free", False)
