from __future__ import annotations

from pathlib import Path

TESTS = Path(__file__).parent
FAKE_WORKER = TESTS / "fake_worker.py"
FAKE_HANDOFF_WORKER = TESTS / "fake_handoff_worker.py"
PDF = b"%PDF-1.4\n% fake test document\n"

import re
from dataclasses import dataclass, field

from app.auth.mailer import Mail


@dataclass
class MemoryMailer:
    sent: list[Mail] = field(default_factory=list)

    def send(self, mail: Mail) -> None:
        self.sent.append(mail)

    def last_to(self, email: str) -> Mail:
        return [mail for mail in self.sent if mail.to == email][-1]


def token_in(mail: Mail) -> str:
    match = re.search(r"token=([\w-]+)", mail.body)
    assert match, mail.body
    return match.group(1)


import time


def upload(client, name="doc.pdf", data=PDF, language="vi", engine=None, model=None, font=None):
    form = {"language": language}
    if engine is not None:
        form["engine"] = engine
    if model is not None:
        form["model"] = model
    if font is not None:
        form["font"] = font
    return client.post("/api/files", files={"file": (name, data, "application/pdf")}, data=form)


def wait_file(client, file_id, statuses=("done", "error"), timeout=15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = client.get(f"/api/files/{file_id}").json()
        if item.get("status") in statuses:
            return item
        time.sleep(0.05)
    raise AssertionError(f"{file_id} không tới trạng thái {statuses}")


import json as _json
import threading
from urllib.parse import urlencode

from app.providers.client import ProviderError, Response  # noqa: E402

GEMINI_MODELS_BODY = {"models": [
    {"name": "models/gemini-3.5-flash-lite", "displayName": "Gemini 3.5 Flash-Lite",
     "supportedGenerationMethods": ["generateContent", "countTokens"]},
    {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.5-flash-tts", "displayName": "Gemini 3.5 Flash TTS", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.5-live-translate", "displayName": "Live", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-001", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-4-exp", "displayName": "Gemini 4 Experimental", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/imagen-4", "displayName": "Imagen", "supportedGenerationMethods": ["predict"]},
]}


def _error_info(reason: str, service: str, **metadata) -> dict:
    return {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "domain": "googleapis.com",
            "metadata": {"service": service, "consumer": "projects/123456789", **metadata}}


def _quota_failure(quota_id: str, model: str = "gemini-3.5-flash-lite") -> dict:
    return {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
        "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
        "quotaId": quota_id, "quotaDimensions": {"location": "global", "model": model}, "quotaValue": "15"}]}


_GL = "generativelanguage.googleapis.com"
_TR = "translate.googleapis.com"
_HELP = {"@type": "type.googleapis.com/google.rpc.Help", "links": [
    {"description": "Learn more about Gemini API quotas", "url": "https://ai.google.dev/gemini-api/docs/rate-limits"}]}
_QUOTA_MESSAGE = ("You exceeded your current quota, please check your plan and billing details. For more information on "
                  "this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.")

# Thân lỗi thật của Google (rút gọn từ phản hồi thực tế của Gemini API v1beta và Cloud Translation v2).
# Tên → (HTTP, body). Không câu nào chứa key — Google không bao giờ trả key về.
GOOGLE_ERRORS: dict[str, tuple[int, dict]] = {
    "gemini_key_invalid": (400, {"error": {
        "code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
        "details": [_error_info("API_KEY_INVALID", _GL),
                    {"@type": "type.googleapis.com/google.rpc.LocalizedMessage", "locale": "en-US",
                     "message": "API key not valid. Please pass a valid API key."}]}}),
    "cloud_key_invalid": (400, {"error": {
        "code": 400, "message": "API key not valid. Please pass a valid API key.",
        "errors": [{"message": "API key not valid. Please pass a valid API key.", "domain": "global", "reason": "badRequest"}],
        "status": "INVALID_ARGUMENT", "details": [_error_info("API_KEY_INVALID", _TR)]}}),
    "legacy_key_invalid": (400, {"error": {
        "code": 400, "message": "Bad Request",
        "errors": [{"message": "Bad Request", "domain": "usageLimits", "reason": "keyInvalid"}]}}),
    "unauthenticated": (401, {"error": {
        "code": 401, "status": "UNAUTHENTICATED",
        "message": "API keys are not supported by this API. Expected OAuth2 access token or other authentication credentials.",
        "details": [_error_info("CREDENTIALS_MISSING", _GL)]}}),
    "gemini_service_disabled": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED",
        "message": "Generative Language API has not been used in project 123456789 before or it is disabled. Enable it by "
                   "visiting https://console.developers.google.com/apis/api/generativelanguage.googleapis.com/overview"
                   "?project=123456789 then retry.",
        "details": [_error_info("SERVICE_DISABLED", _GL, activationUrl="https://console.developers.google.com/apis/api/"
                                "generativelanguage.googleapis.com/overview?project=123456789")]}}),
    "cloud_access_not_configured": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED",
        "message": "Cloud Translation API has not been used in project 123456789 before or it is disabled.",
        "errors": [{"message": "Cloud Translation API has not been used in project 123456789 before or it is disabled.",
                    "domain": "usageLimits", "reason": "accessNotConfigured",
                    "extendedHelp": "https://console.developers.google.com"}]}}),
    "cloud_billing_disabled": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED",
        "message": "This API method requires billing to be enabled. Please enable billing on project #123456789 by "
                   "visiting https://console.developers.google.com/billing/enable?project=123456789 then retry.",
        "details": [_error_info("BILLING_DISABLED", _TR)]}}),
    "gemini_billing_disabled": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED", "message": "This API method requires billing to be enabled.",
        "details": [_error_info("BILLING_DISABLED", _GL)]}}),
    "cloud_service_blocked": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED",
        "message": "Requests to this API translate.googleapis.com method "
                   "google.cloud.translation.v2.TranslateService.TranslateText are blocked.",
        "details": [_error_info("API_KEY_SERVICE_BLOCKED", _TR, methodName="google.cloud.translation.v2.TranslateService.TranslateText")]}}),
    "gemini_ip_blocked": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED",
        "message": "The provided API key has an IP address restriction. The originating IP address of the call "
                   "(203.0.113.7) violates this restriction.",
        "details": [_error_info("API_KEY_IP_ADDRESS_BLOCKED", _GL)]}}),
    "gemini_referrer_blocked": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED", "message": "Requests from referer <empty> are blocked.",
        "details": [_error_info("API_KEY_HTTP_REFERRER_BLOCKED", _GL)]}}),
    "gemini_per_minute": (429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED", "message": _QUOTA_MESSAGE,
        "details": [_quota_failure("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"), _HELP,
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "13s"}]}}),
    "gemini_per_day": (429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED", "message": _QUOTA_MESSAGE,
        "details": [_quota_failure("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), _HELP,
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"}]}}),
    "cloud_rate_limit": (429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": "Quota exceeded for quota metric 'v2 and v3 general model characters' and limit 'v2 and v3 general "
                   "model characters per minute per user' of service 'translate.googleapis.com' for consumer "
                   "'project_number:123456789'.",
        "details": [_error_info("RATE_LIMIT_EXCEEDED", _TR, quota_metric="translate.googleapis.com/default",
                                quota_limit="DefaultRequestsPerMinutePerUser")]}}),
    "cloud_per_day": (429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": "Quota exceeded for quota metric 'v2 and v3 general model characters' and limit 'v2 and v3 general "
                   "model characters per day' of service 'translate.googleapis.com' for consumer 'project_number:123456789'.",
        "details": [_error_info("RATE_LIMIT_EXCEEDED", _TR, quota_metric="translate.googleapis.com/default",
                                quota_limit="CharactersPerDayPerProject")]}}),
    "cloud_user_rate_limit": (403, {"error": {
        "code": 403, "message": "User Rate Limit Exceeded",
        "errors": [{"message": "User Rate Limit Exceeded", "domain": "usageLimits", "reason": "userRateLimitExceeded"}]}}),
    "cloud_daily_limit": (403, {"error": {
        "code": 403, "message": "Daily Limit Exceeded",
        "errors": [{"message": "Daily Limit Exceeded", "domain": "usageLimits", "reason": "dailyLimitExceeded"}]}}),
    "gemini_model_not_found": (404, {"error": {
        "code": 404, "status": "NOT_FOUND",
        "message": "models/gemini-3.0-flash is not found for API version v1beta, or is not supported for generateContent. "
                   "Call ListModels to see the list of available models and their supported methods."}}),
    "gemini_invalid_argument": (400, {"error": {
        "code": 400, "status": "INVALID_ARGUMENT",
        "message": "Invalid JSON payload received. Unknown name \"thinkingConfig\" at 'generation_config': Cannot find field.",
        "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [{
            "field": "generation_config",
            "description": "Invalid JSON payload received. Unknown name \"thinkingConfig\" at 'generation_config'."}]}]}}),
    "gemini_location": (400, {"error": {
        "code": 400, "status": "FAILED_PRECONDITION", "message": "User location is not supported for the API use."}}),
    "cloud_invalid_value": (400, {"error": {
        "code": 400, "message": "Invalid Value",
        "errors": [{"message": "Invalid Value", "domain": "global", "reason": "invalid"}]}}),
    "gemini_permission_denied": (403, {"error": {
        "code": 403, "status": "PERMISSION_DENIED", "message": "Your API key was reported as leaked. Please use another API key."}}),
    "gemini_overloaded": (503, {"error": {
        "code": 503, "status": "UNAVAILABLE", "message": "The model is overloaded. Please try again later."}}),
    "internal": (500, {"error": {"code": 500, "status": "INTERNAL", "message": "An internal error has occurred."}}),
}


def gemini_reply(items: list) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": _json.dumps(items, ensure_ascii=False)}]}}]}


def gemini_segments(payload: dict) -> list[str]:
    return _json.loads(payload["contents"][0]["parts"][0]["text"])


def gemini_echo(transform=lambda text: "VI " + text):
    """Handler cho FakeTransport: 'dịch' từng đoạn trong request bằng `transform`, bất kể thứ tự lô."""
    def handler(method, url, headers, payload):
        return 200, gemini_reply([transform(text) for text in gemini_segments(payload)])
    return handler


def cloud_reply(items: list) -> dict:
    return {"data": {"translations": [{"translatedText": text} for text in items]}}


class FakeTransport:
    """Transport giả cho app.providers.client — không có mạng. `replies`: hàng đợi (status, body),
    (status, body, headers) hoặc Exception dùng theo thứ tự; `handler(method, url, headers, json) -> (status, body)` khi cần logic.
    Ghi lại mọi request vào `calls` (an toàn với luồng: translate_segments gọi song song)."""

    def __init__(self, *replies, handler=None) -> None:
        self.replies, self.handler, self.calls = list(replies), handler, []
        self._lock = threading.Lock()

    def get(self, url, *, headers, params=None, timeout):
        return self._answer("GET", f"{url}?{urlencode(params)}" if params else url, headers, None, timeout)

    def post(self, url, *, headers, json, timeout):
        return self._answer("POST", url, headers, json, timeout)

    def _answer(self, method, url, headers, payload, timeout):
        with self._lock:
            self.calls.append({"method": method, "url": url, "headers": dict(headers), "json": payload, "timeout": timeout})
            if self.handler is not None:
                reply = self.handler(method, url, headers, payload)
            elif self.replies:
                reply = self.replies.pop(0)
            else:
                raise AssertionError("FakeTransport: hết câu trả lời")
        if isinstance(reply, Exception):
            raise reply
        status, body, *rest = reply  # (status, body) hoặc (status, body, headers)
        headers = {name.lower(): value for name, value in (rest[0] if rest else {}).items()}
        return Response(status, body, _json.dumps(body), headers)


def save_key(client, provider="gemini", key="AIza-test-key-0001") -> dict:
    """Lưu key qua API với transport giả trả lời OK; trả về settings JSON."""
    body = GEMINI_MODELS_BODY if provider == "gemini" else cloud_reply(["ok"])
    client.app.state.provider_transport = FakeTransport((200, body))
    response = client.put(f"/api/settings/credentials/{provider}", json={"api_key": key})
    assert response.status_code == 200, response.text
    return response.json()


from contextlib import contextmanager
from dataclasses import replace as _replace
from datetime import timedelta as _timedelta
import uuid as _uuid

from fastapi.testclient import TestClient  # noqa: E402

from app.db import utcnow as _utcnow  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import User as _User  # noqa: E402
from app.security import hash_password as _hash_password  # noqa: E402

ADMIN_EMAIL, ADMIN_PASSWORD = "admin@example.com", "mat-khau-admin-9"
ADMIN_HASH = _hash_password(ADMIN_PASSWORD)  # băm một lần cho cả phiên test (argon2 đắt)


def seed_admin(client) -> str:
    """Chèn thẳng một quản trị viên đã xác nhận vào DB (không qua /api/setup, không tốn hạn mức IP) — bảng users trống
    thì register/login đóng (spec 2026-10-05 §2). created_at lùi một ngày: luôn là người "cũ nhất"."""
    with client.app.state.session_factory() as db:
        user = _User(id=_uuid.uuid4().hex, email=ADMIN_EMAIL, password_hash=ADMIN_HASH, email_verified_at=_utcnow(),
                     is_admin=True, created_at=_utcnow() - _timedelta(days=1))
        db.add(user)
        db.commit()
        return user.id


def login_admin(client) -> dict:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def bare_client(settings, mailer=None, *, seed=True, base_url="https://testserver", **overrides):
    """App không tiêm mailer (trừ khi truyền): thư đi đường DB → env → MAIL_DEV_LOG → log thật. `seed=False` = instance trống.
    `base_url` = địa chỉ trình duyệt gọi tới (POST /api/setup ghi nó làm địa chỉ trang)."""
    app = create_app(_replace(settings, **overrides) if overrides else settings, mailer=mailer)
    with TestClient(app, base_url=base_url, headers={"X-Requested-With": "fetch"}) as client:
        if seed:
            seed_admin(client)
        yield client


class SmtpEvents(list):
    """Các bước SMTP giả đã ghi; `raise_on_login` = ngoại lệ ném ở bước login (test thư thử thất bại);
    `contexts` = (bước, ssl context) truyền vào SMTP_SSL / starttls — None nghĩa là không kiểm chứng chỉ."""

    raise_on_login: BaseException | None = None

    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[tuple[str, object]] = []


def fake_smtp(monkeypatch) -> SmtpEvents:
    """Thay smtplib.SMTP / SMTP_SSL bằng lớp giả ghi lại từng bước: (lớp, host, port, timeout) → starttls → login → send → quit."""
    events = SmtpEvents()

    def make(kind):
        class Fake:
            def __init__(self, host, port, timeout, context=None):
                events.append((kind, host, port, timeout))
                if kind == "SMTP_SSL":
                    events.contexts.append((kind, context))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                events.append(("quit",))

            def starttls(self, context=None):
                events.append(("starttls",))
                events.contexts.append(("starttls", context))

            def login(self, user, password):
                events.append(("login", user, password))
                if events.raise_on_login is not None:
                    raise events.raise_on_login

            def send_message(self, message):
                events.append(("send", message["To"], message["Subject"], message["From"]))

        return Fake

    monkeypatch.setattr("app.auth.mailer.smtplib.SMTP", make("SMTP"))
    monkeypatch.setattr("app.auth.mailer.smtplib.SMTP_SSL", make("SMTP_SSL"))
    return events
