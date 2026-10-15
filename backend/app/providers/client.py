"""Gọi Google (Gemini / Cloud Translation v2) — kiểm key và dịch danh sách đoạn.

Module này chạy ở CẢ hai tiến trình: web (kiểm key lúc lưu) và worker handoff (dịch). Vì vậy
không import FastAPI/SQLAlchemy ở đây. Mọi HTTP đi qua `Transport` để test tiêm bản giả;
`RequestsTransport` là bản thật. Key luôn nằm trong header — không bao giờ ở URL hay thông điệp lỗi.
"""

from __future__ import annotations

import html
import json
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Protocol

from ..files.languages import ENGLISH_NAMES
from .catalog import EXCLUDED_MODEL_WORDS

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
CLOUD_URL = "https://translation.googleapis.com/language/translate/v2"
TIMEOUT = 15  # kiểm key (lúc lưu): một request nhỏ, người dùng đang đợi
# Dịch: generateContent không stream chỉ trả lời khi dịch xong CẢ lô → (kết nối, đọc) = (10 s, 120 s).
# Hết giờ đọc thì Google có thể vẫn đang dịch (và tính tiền) lô đó → chỉ thử lại READ_TIMEOUT_RETRIES lần.
TRANSLATE_TIMEOUT: tuple[float, float] = (10, 120)
READ_TIMEOUT_RETRIES = 1
# Không bắt đầu lần thử mới khi đã qua ngần này giây kể từ lần gửi đầu của request: lần thử cuối
# tốn tối đa sum(TRANSLATE_TIMEOUT) → một request xấu nhất ≈ 180 + 130 = 310 s, dưới hẳn JOB_STALL
# (8 phút, đồng hồ "không nhích" của runner — mỗi lô xong mới có một dòng tiến độ).
RETRY_BUDGET = 180
RATE_LIMIT_ATTEMPTS = 6  # bị giới hạn tốc độ: tối đa 6 lần gửi (5 lần chờ) rồi mới báo rate_limited
MAX_WAIT = 60  # trần cho một lần chờ (kể cả khi Google gợi ý lâu hơn)
BATCH_SEGMENTS = 40
BATCH_CHARS = 8000
PARALLEL = 4
BACKOFF: tuple[int, ...] = (2, 4, 8, 16)

# Phân loại lỗi Google theo thân JSON (error.status, ErrorInfo.reason, QuotaFailure.quotaId, errors[].reason
# kiểu cũ của Cloud Translation v2) cộng mã HTTP — mỗi nguyên nhân một mã, người dùng biết phải sửa gì.
INVALID_KEY_REASONS = frozenset({"API_KEY_INVALID", "keyInvalid"})
API_DISABLED_REASONS = frozenset({"SERVICE_DISABLED", "accessNotConfigured"})
BILLING_REASONS = frozenset({"BILLING_DISABLED"})
KEY_RESTRICTED_REASONS = frozenset({
    "API_KEY_SERVICE_BLOCKED", "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED",
    "API_KEY_ANDROID_APP_BLOCKED", "API_KEY_IOS_APP_BLOCKED",
})
RATE_LIMIT_REASONS = frozenset({"RATE_LIMIT_EXCEEDED", "userRateLimitExceeded", "rateLimitExceeded"})
DAILY_LIMIT_REASONS = frozenset({"dailyLimitExceeded"})
RETRYABLE = frozenset({"rate_limited", "provider_unavailable"})  # còn lại: nguyên nhân cố định, thử lại vô ích
# Lúc lưu key: các mã này → 400 kèm đúng mã (người dùng tự sửa key/project được); mọi mã khác → 502.
KEY_CHECK_REJECTIONS = frozenset({"invalid_api_key", "api_not_enabled", "billing_disabled", "key_restricted", "provider_rejected"})
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:@/-]")

# Cùng biểu thức với pdf2zh/translator.py: thẻ công thức </?bN> phải giữ nguyên thứ tự, thẻ kiểu <sN> phải cân.
PLACEHOLDER = re.compile(r"</?b\d+>")
STYLE_TAG = re.compile(r"<(/?)s([123])>", re.IGNORECASE)
KEPT_TAG = re.compile(r"</?b\d+>|</?s[123]>", re.IGNORECASE)  # thẻ của lõi: gửi nguyên dạng cho Cloud (format=html)

SYSTEM_PROMPT = (
    "You are a professional document translator. The user message is a JSON array of text segments "
    "taken from a PDF. Translate every segment into {language}. Each segment may contain tags such as "
    "<b0>, </b0>, <b12></b12>, <s1>, </s1>: keep every tag exactly as in the source — same tags, same "
    "count, same order — and translate only the text around them. Do not add explanations, notes, "
    "numbering or extra elements. Reply with a JSON array of strings of exactly the same length and "
    "order as the input, one translation per input segment."
)


def system_instruction(language: str, instructions: str = "") -> str:
    """systemInstruction của Gemini: SYSTEM_PROMPT (luật định dạng) rồi chỉ dẫn văn phong (spec 2026-10-14 §4) nếu có.
    Không có chỉ dẫn → y hệt trước đây. Chỉ SYSTEM_PROMPT đi qua str.format: chỉ dẫn chứa văn bản tự do của người
    dùng (có thể có "{", "{language}"…) nên được nối nguyên văn SAU khi format, không bao giờ format phần ghép."""
    prompt = SYSTEM_PROMPT.format(language=language)
    return f"{prompt}\n\n{instructions}" if instructions else prompt


def _stderr(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def _token(value: object) -> str:
    """Một từ an toàn để ghi log: chỉ ký tự kiểu định danh, tối đa 80 — không bao giờ là câu văn."""
    return _UNSAFE.sub("", str(value or ""))[:80]


class ProviderError(Exception):
    """code: invalid_api_key | api_not_enabled | billing_disabled | key_restricted | rate_limited |
    quota_exceeded | model_unavailable | provider_rejected | provider_unavailable.
    `detail`/`status`/`reason` không được chứa key hay văn bản (chỉ tên lỗi, mã của Google)."""

    def __init__(self, code: str, detail: str = "", *, http: int | None = None, status: str = "", reason: str = "",
                 retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.http, self.status, self.reason = http, status, reason
        self.retry_after = retry_after  # giây Google bảo chờ (RetryInfo.retryDelay / Retry-After), nếu có

    def diagnostic(self, provider: str, *, secret: str = "") -> str:
        """Một dòng chẩn đoán cho stderr: `provider=… http=… status=… reason=…` — không thân lỗi, không key."""
        fields = {"provider": provider, "http": self.http, "status": self.status, "reason": self.reason or self.detail}
        line = " ".join(f"{name}={_token(value) or '-'}" for name, value in fields.items())
        return line.replace(secret, "***") if secret else line


@dataclass
class Response:
    status: int
    body: object  # JSON đã phân tích, hoặc None
    text: str
    headers: dict[str, str] = field(default_factory=dict)  # tên viết thường; chỉ giữ những header cần đọc


Timeout = float | tuple[float, float]  # requests: một số, hoặc (kết nối, đọc)


class Transport(Protocol):
    def get(self, url: str, *, headers: dict, params: dict | None = None, timeout: Timeout) -> Response: ...

    def post(self, url: str, *, headers: dict, json: object, timeout: Timeout) -> Response: ...


class RequestsTransport:
    def __init__(self, session=None) -> None:
        import requests  # import muộn: web app không cần requests cho tới khi có người lưu key

        self._requests = requests
        self._session = session or requests.Session()

    def get(self, url, *, headers, params=None, timeout):
        return self._send("GET", url, headers=headers, params=params, timeout=timeout)

    def post(self, url, *, headers, json, timeout):
        return self._send("POST", url, headers=headers, json=json, timeout=timeout)

    def _send(self, method, url, **kwargs) -> Response:
        try:
            raw = self._session.request(method, url, **kwargs)
        except self._requests.RequestException as error:
            # Chỉ giữ LOẠI lỗi: chuỗi lỗi của requests có thể chứa URL/thân request.
            raise ProviderError("provider_unavailable", type(error).__name__, reason=type(error).__name__) from None
        try:
            body = raw.json()
        except ValueError:
            body = None
        headers = {"retry-after": raw.headers["Retry-After"]} if "Retry-After" in raw.headers else {}
        return Response(raw.status_code, body, raw.text[:2000], headers)


# ---- Lỗi của Google ---------------------------------------------------------------------


@dataclass
class GoogleError:
    http: int
    status: str = ""
    reasons: tuple[str, ...] = ()  # ErrorInfo.reason trước, rồi errors[].reason kiểu cũ
    quota_ids: tuple[str, ...] = ()  # QuotaFailure.violations[].quotaId + ErrorInfo.metadata.quota_limit
    retry_delay: float | None = None  # RetryInfo.retryDelay ("13s") tính bằng giây
    message: str = ""  # CHỈ để phân loại (không bao giờ ghi ra đâu cả)


def _seconds(value: object) -> float | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*s?\s*", str(value or ""))
    return float(match.group(1)) if match else None


def parse_google_error(response: Response) -> GoogleError:
    body = response.body
    if isinstance(body, list) and body and isinstance(body[0], dict):
        body = body[0]  # vài endpoint bọc lỗi trong mảng
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return GoogleError(response.status)
    reasons: list[str] = []
    quota_ids: list[str] = []
    retry_delay = None
    for detail in error.get("details") or []:
        if not isinstance(detail, dict):
            continue
        kind = str(detail.get("@type", ""))
        if kind.endswith("google.rpc.ErrorInfo"):
            reasons.append(str(detail.get("reason") or ""))
            metadata = detail.get("metadata")
            if isinstance(metadata, dict) and metadata.get("quota_limit"):
                quota_ids.append(str(metadata["quota_limit"]))
        elif kind.endswith("google.rpc.QuotaFailure"):
            for violation in detail.get("violations") or []:
                if isinstance(violation, dict) and violation.get("quotaId"):
                    quota_ids.append(str(violation["quotaId"]))
        elif kind.endswith("google.rpc.RetryInfo"):
            retry_delay = _seconds(detail.get("retryDelay"))
    for item in error.get("errors") or []:
        if isinstance(item, dict):
            reasons.append(str(item.get("reason") or ""))
    return GoogleError(response.status, str(error.get("status") or ""), tuple(r for r in reasons if r),
                       tuple(quota_ids), retry_delay, str(error.get("message") or ""))


def error_code(info: GoogleError) -> str:
    reasons = set(info.reasons)
    if reasons & DAILY_LIMIT_REASONS or any("perday" in quota.lower() for quota in info.quota_ids):
        return "quota_exceeded"  # hết hạn mức NGÀY: chờ vài giây cũng vô ích
    if info.http == 429 or reasons & RATE_LIMIT_REASONS or info.status == "RESOURCE_EXHAUSTED":
        return "rate_limited"
    if info.http == 401 or reasons & INVALID_KEY_REASONS:
        return "invalid_api_key"
    if reasons & API_DISABLED_REASONS:
        return "api_not_enabled"
    if reasons & BILLING_REASONS:
        return "billing_disabled"
    if reasons & KEY_RESTRICTED_REASONS:
        return "key_restricted"
    if info.http == 404:
        return "model_unavailable"
    if info.http >= 500:
        return "provider_unavailable"
    if info.http == 400 and info.message.startswith(("API key not valid", "API key expired")):
        return "invalid_api_key"  # thân lỗi kiểu cũ không có ErrorInfo: chỉ còn câu báo lỗi để nhận ra
    return "provider_rejected"


def classify(response: Response) -> ProviderError:
    info = parse_google_error(response)
    reason = next(iter(info.reasons), "") or next(iter(info.quota_ids), "")
    retry_after = info.retry_delay if info.retry_delay is not None else _seconds(response.headers.get("retry-after"))
    return ProviderError(error_code(info), http=info.http, status=info.status, reason=reason, retry_after=retry_after)


# ---- Kiểm key -------------------------------------------------------------------------


def gemini_models_from(body: object) -> list[dict]:
    models: list[dict] = []
    for item in (body.get("models", []) if isinstance(body, dict) else []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        if not name.startswith("models/gemini") or "generateContent" not in (item.get("supportedGenerationMethods") or []):
            continue
        model_id = name[len("models/"):]
        if any(word in model_id.lower() for word in EXCLUDED_MODEL_WORDS):
            continue
        models.append({"id": model_id, "label": str(item.get("displayName") or model_id)})
    return models


def verify_key(provider: str, api_key: str, transport: Transport) -> list[dict]:
    """Gọi nhà cung cấp một lần (không thử lại); lỗi → ProviderError đã phân loại theo thân lỗi của Google."""
    if provider == "gemini":
        response = transport.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": api_key},
                                 params={"pageSize": 1000}, timeout=TIMEOUT)
    elif provider == "google_cloud":
        response = transport.post(CLOUD_URL, headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
                                  json={"q": ["ok"], "target": "vi", "format": "text"}, timeout=TIMEOUT)
    else:
        raise ValueError(f"provider lạ: {provider}")
    if response.status != 200:
        raise classify(response)
    return gemini_models_from(response.body) if provider == "gemini" else []


# ---- Kiểm thẻ ------------------------------------------------------------------------


def _style_counts(text: str) -> Counter | None:
    stack: list[str] = []
    pairs: Counter = Counter()
    for match in STYLE_TAG.finditer(text):
        closing, identifier = match.groups()
        if not closing:
            stack.append(identifier)
        elif not stack or stack[-1] != identifier:
            return None
        else:
            stack.pop()
            pairs[identifier] += 1
    return None if stack else pairs


def tags_match(source: str, translated: str) -> bool:
    if PLACEHOLDER.findall(source) != PLACEHOLDER.findall(translated):
        return False
    before, after = _style_counts(source), _style_counts(translated)
    return before is not None and before == after


# ---- Dịch theo lô --------------------------------------------------------------------


def make_batches(segments: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    chars = 0
    for text in segments:
        if current and (len(current) >= BATCH_SEGMENTS or chars + len(text) > BATCH_CHARS):
            batches.append(current)
            current, chars = [], 0
        current.append(text)
        chars += len(text)
    if current:
        batches.append(current)
    return batches


class _Gate:
    """Giới hạn số request đang bay của MỘT job. `narrow()` hạ về 1 cho phần còn lại của job (sau lần
    đầu bị giới hạn tốc độ); `stop()` (lỗi chết người) đánh thức mọi request đang đợi để chúng bỏ cuộc."""

    def __init__(self, limit: int, abort: threading.Event) -> None:
        self.limit, self.active, self.waiting = limit, 0, 0
        self.abort = abort
        self.changed = threading.Condition()

    def narrow(self) -> None:
        with self.changed:
            self.limit = 1

    def stop(self) -> None:
        with self.changed:
            self.abort.set()
            self.changed.notify_all()

    @contextmanager
    def slot(self) -> Iterator[None]:
        with self.changed:
            self.waiting += 1
            self.changed.notify_all()
            try:
                self.changed.wait_for(lambda: self.active < self.limit or self.abort.is_set())
            finally:
                self.waiting -= 1
            if self.abort.is_set():
                raise ProviderError("provider_unavailable", "aborted")
            self.active += 1
        try:
            yield
        finally:
            with self.changed:
                self.active -= 1
                self.changed.notify_all()


class _Client:
    """Một job dịch: giữ key/model/transport; `gate` giới hạn số request song song, và cờ `abort` của nó
    dừng mọi lô khi gặp lỗi chết người."""

    def __init__(self, api_key: str, model: str, target_language: str, transport: Transport,
                 sleep: Callable[[float], None] | None, clock: Callable[[], float], log: Callable[[str], None],
                 instructions: str = "") -> None:
        self.api_key, self.model, self.transport, self.clock, self.log = api_key, model, transport, clock, log
        self.language_code = target_language
        self.language = ENGLISH_NAMES.get(target_language, target_language)
        self.instructions = instructions  # chỉ dẫn văn phong (chỉ _Gemini dùng); nội dung người dùng — không ghi log
        self.abort = threading.Event()
        self.gate = _Gate(PARALLEL, self.abort)
        # Mặc định chờ trên cờ abort: một lô khác hỏng chết người thì lần chờ (tới 60 s) dừng ngay.
        self.sleep = sleep or self.abort.wait

    def translate_chunk(self, segments: list[str]) -> dict[str, str]:
        parsed = self._request(segments)
        if parsed is None:  # sai độ dài / JSON hỏng: chia đôi; một đoạn vẫn hỏng → bỏ
            if len(segments) == 1:
                return {}
            middle = len(segments) // 2
            return {**self.translate_chunk(segments[:middle]), **self.translate_chunk(segments[middle:])}
        return {src: dst for src, dst in zip(segments, parsed) if isinstance(dst, str) and dst and tags_match(src, dst)}

    def _post(self, url: str, headers: dict, body: dict) -> Response:
        attempt = transient = rate_limits = read_timeouts = 0  # attempt: số lần đã chờ (chỉ số BACKOFF)
        started: float | None = None
        while True:
            response: Response | None = None
            with self.gate.slot():  # ném "aborted" khi job đã hỏng
                if started is None:
                    started = self.clock()
                try:
                    response = self.transport.post(url, headers=headers, json=body, timeout=TRANSLATE_TIMEOUT)
                except ProviderError as error:
                    failure = error
            if response is not None:
                if response.status < 400:
                    return response
                failure = classify(response)
                if failure.code not in RETRYABLE:
                    raise failure  # nguyên nhân cố định (key, API, hạn mức ngày…): thử lại vô ích
            if failure.code == "rate_limited":
                self.gate.narrow()  # phần còn lại của job: một request một lúc
                rate_limits += 1
                if rate_limits >= RATE_LIMIT_ATTEMPTS:
                    raise failure
                hint = failure.retry_after
                wait = min(MAX_WAIT, max(1.0, hint)) if hint is not None else BACKOFF[min(attempt, len(BACKOFF) - 1)]
            else:  # 5xx / mạng
                transient += 1
                if (failure.reason or failure.detail) == "ReadTimeout":
                    read_timeouts += 1
                    if read_timeouts > READ_TIMEOUT_RETRIES:
                        raise failure  # có thể Google vẫn đang dịch (và tính tiền) lô đó
                if transient > len(BACKOFF):
                    raise failure
                wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            if self.clock() - started + wait > RETRY_BUDGET:
                raise failure
            self.sleep(wait)
            attempt += 1

    def _request(self, segments: list[str]) -> list | None:
        raise NotImplementedError


def _reply_text(body: object) -> str:
    """Ghép mọi phần `text` của ứng viên đầu, BỎ phần suy nghĩ (`thought: true`) — model 3.x có thể trả
    câu trả lời thành nhiều phần, và phần đầu có thể là suy nghĩ chứ không phải JSON."""
    parts = body["candidates"][0]["content"]["parts"]  # type: ignore[index]
    return "".join(part["text"] for part in parts if isinstance(part, dict) and "text" in part and part.get("thought") is not True)


def _finish_reason(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    candidates = body.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        return str(candidates[0].get("finishReason") or "")
    feedback = body.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return f"blocked:{feedback['blockReason']}"
    return ""


class _Gemini(_Client):
    def _generation_config(self) -> dict:
        config: dict = {"responseMimeType": "application/json", "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}}}
        # Gemini 3.x: Google khuyên để temperature mặc định (1.0) — hạ xuống có thể làm model lặp/kẹt. KHÔNG
        # gửi thinkingConfig: dạng tham số cho 3.5/3.8 chưa kiểm chứng, một trường lạ là 400 cho MỌI request.
        if not self.model.startswith("gemini-3"):
            config["temperature"] = 0.2
        return config

    def _request(self, segments: list[str]) -> list | None:
        body = {
            "systemInstruction": {"parts": [{"text": system_instruction(self.language, self.instructions)}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(segments, ensure_ascii=False)}]}],
            "generationConfig": self._generation_config(),
        }
        response = self._post(f"{GEMINI_BASE}/models/{self.model}:generateContent",
                              {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}, body)
        parsed: object = None
        try:
            parsed = json.loads(_reply_text(response.body))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        if isinstance(parsed, list) and len(parsed) == len(segments):
            return parsed
        # Một dòng chẩn đoán (không văn bản): vì sao lô này phải chia đôi / bỏ — MAX_TOKENS, SAFETY, sai độ dài…
        items = len(parsed) if isinstance(parsed, list) else "-"
        self.log(f"provider=gemini reply=unparsable finishReason={_token(_finish_reason(response.body)) or '-'} "
                 f"batch={len(segments)} items={items}")
        return None


def escape_outside_tags(text: str) -> str:
    """HTML-escape &, <, > của văn bản, trừ thẻ <bN>/</bN>/<sN>/</sN> của lõi — "a < b" gửi thô với
    format=html thì Google coi "<" là mở thẻ và làm hỏng câu. html.unescape lúc nhận trả lại nguyên dạng."""
    pieces, last = [], 0
    for match in KEPT_TAG.finditer(text):
        pieces += [html.escape(text[last:match.start()], quote=False), match.group(0)]
        last = match.end()
    pieces.append(html.escape(text[last:], quote=False))
    return "".join(pieces)


class _Cloud(_Client):
    def _request(self, segments: list[str]) -> list | None:
        # format=html: Cloud giữ nguyên thẻ <bN> thay vì dịch/tách chúng; văn bản quanh thẻ phải escape.
        body = {"q": [escape_outside_tags(text) for text in segments], "target": self.language_code, "format": "html"}
        response = self._post(CLOUD_URL, {"X-Goog-Api-Key": self.api_key, "Content-Type": "application/json"}, body)
        try:
            parsed = [html.unescape(str(item["translatedText"])) for item in response.body["data"]["translations"]]
        except (KeyError, TypeError):
            return None
        return parsed if len(parsed) == len(segments) else None


_CLIENTS: dict[str, type[_Client]] = {"gemini": _Gemini, "google_cloud": _Cloud}


def translate_segments(
    provider: str, api_key: str, model: str, target_language: str, segments: list[str], *,
    transport: Transport, on_progress: Callable[[int, int], None] | None = None,
    on_batch: Callable[[dict[str, str]], None] | None = None,
    sleep: Callable[[float], None] | None = None, clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = _stderr, instructions: str = "",
) -> dict[str, str]:
    """Dịch `segments` → {src: dst} cho các đoạn dịch được. `on_batch` nhận bảng của từng lô ngay khi lô
    đó xong (để người gọi ghi lại phần đã trả tiền). Ném ProviderError khi gặp lỗi chết người (các lô
    khác dừng theo) — nhưng lô nào đã xong vẫn được giao qua `on_batch` trước khi ném.
    `instructions` (chỉ Gemini dùng; Cloud Translation bỏ qua) nối sau SYSTEM_PROMPT — xem system_instruction."""
    client = _CLIENTS[provider](api_key, model, target_language, transport, sleep, clock, log, instructions)
    batches = make_batches(segments)
    total, done = len(segments), 0
    table: dict[str, str] = {}
    failure: ProviderError | None = None
    if on_progress:
        on_progress(0, total)
    pool = ThreadPoolExecutor(max_workers=PARALLEL)
    try:
        futures = {pool.submit(client.translate_chunk, batch): batch for batch in batches}
        for future in as_completed(futures):
            try:
                chunk = future.result()
            except ProviderError as error:
                if failure is None:
                    failure = error
                    client.gate.stop()  # các lô khác bỏ cuộc ở lần gửi/lần chờ kế tiếp
                continue
            table.update(chunk)
            done += len(futures[future])
            if on_batch:
                on_batch(chunk)
            if on_progress:
                on_progress(done, total)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if failure is not None:
        raise failure
    return table
