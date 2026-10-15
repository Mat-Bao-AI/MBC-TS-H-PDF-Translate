import json

import pytest

from app.providers.client import (
    BACKOFF, BATCH_SEGMENTS, CLOUD_URL, GEMINI_BASE, SYSTEM_PROMPT, ProviderError, gemini_models_from, make_batches,
    tags_match, translate_segments, verify_key,
)
from helpers import (
    GEMINI_MODELS_BODY, GOOGLE_ERRORS, FakeTransport, cloud_reply, gemini_echo, gemini_reply, gemini_segments,
)

KEY = "AIza-test-key-0001"
NO_SLEEP = lambda seconds: None  # noqa: E731


def test_verify_gemini_key_lists_usable_text_models():
    transport = FakeTransport((200, GEMINI_MODELS_BODY))
    models = verify_key("gemini", KEY, transport)
    assert [m["id"] for m in models] == ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-exp"]
    assert models[0]["label"] == "Gemini 3.5 Flash-Lite"
    [call] = transport.calls
    assert call["method"] == "GET" and call["url"] == f"{GEMINI_BASE}/models?pageSize=1000"
    assert call["headers"]["x-goog-api-key"] == KEY and KEY not in call["url"]


def test_model_list_skips_computer_use_and_robotics_models():
    body = {"models": [
        {"name": "models/gemini-3.5-flash", "displayName": "Gemini 3.5 Flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-computer-use-preview-10-2025", "displayName": "Gemini 2.5 Computer Use Preview",
         "supportedGenerationMethods": ["generateContent", "countTokens"]},
        {"name": "models/gemini-robotics-er-1.5-preview", "displayName": "Gemini Robotics-ER 1.5 Preview",
         "supportedGenerationMethods": ["generateContent"]},
    ]}
    assert [m["id"] for m in gemini_models_from(body)] == ["gemini-3.5-flash"]


def test_verify_cloud_key_posts_a_probe_with_the_key_in_a_header():
    transport = FakeTransport((200, cloud_reply(["ok"])))
    assert verify_key("google_cloud", KEY, transport) == []
    [call] = transport.calls
    assert call["method"] == "POST" and call["url"] == CLOUD_URL and KEY not in call["url"]
    assert call["headers"]["X-Goog-Api-Key"] == KEY
    assert call["json"] == {"q": ["ok"], "target": "vi", "format": "text"}


# (provider, tên thân lỗi trong GOOGLE_ERRORS, mã) — lỗi KHÔNG thử lại: mỗi nguyên nhân một mã riêng.
CAUSES = [
    ("gemini", "gemini_key_invalid", "invalid_api_key"),
    ("google_cloud", "cloud_key_invalid", "invalid_api_key"),
    ("google_cloud", "legacy_key_invalid", "invalid_api_key"),
    ("gemini", "unauthenticated", "invalid_api_key"),
    ("gemini", "gemini_service_disabled", "api_not_enabled"),
    ("google_cloud", "cloud_access_not_configured", "api_not_enabled"),
    ("google_cloud", "cloud_billing_disabled", "billing_disabled"),
    ("gemini", "gemini_billing_disabled", "billing_disabled"),
    ("google_cloud", "cloud_service_blocked", "key_restricted"),
    ("gemini", "gemini_ip_blocked", "key_restricted"),
    ("gemini", "gemini_referrer_blocked", "key_restricted"),
    ("gemini", "gemini_per_day", "quota_exceeded"),
    ("google_cloud", "cloud_per_day", "quota_exceeded"),
    ("google_cloud", "cloud_daily_limit", "quota_exceeded"),
    ("gemini", "gemini_model_not_found", "model_unavailable"),
    ("gemini", "gemini_invalid_argument", "provider_rejected"),
    ("gemini", "gemini_location", "provider_rejected"),
    ("google_cloud", "cloud_invalid_value", "provider_rejected"),
    ("gemini", "gemini_permission_denied", "provider_rejected"),
]


@pytest.mark.parametrize(("provider", "name", "code"), CAUSES)
def test_translate_errors_are_classified_from_the_google_body_without_retrying(provider, name, code):
    transport = FakeTransport(GOOGLE_ERRORS[name])
    with pytest.raises(ProviderError) as caught:
        translate_segments(provider, KEY, "gemini-3.5-flash-lite", "vi", ["x"], transport=transport, sleep=NO_SLEEP)
    assert caught.value.code == code
    assert len(transport.calls) == 1  # nguyên nhân cố định: thử lại chỉ tốn tiền/thời gian


@pytest.mark.parametrize(("provider", "name", "code"), [
    ("gemini", "gemini_key_invalid", "invalid_api_key"),
    ("google_cloud", "cloud_key_invalid", "invalid_api_key"),
    ("gemini", "unauthenticated", "invalid_api_key"),
    ("gemini", "gemini_service_disabled", "api_not_enabled"),
    ("google_cloud", "cloud_access_not_configured", "api_not_enabled"),
    ("google_cloud", "cloud_billing_disabled", "billing_disabled"),
    ("google_cloud", "cloud_service_blocked", "key_restricted"),
    ("gemini", "gemini_ip_blocked", "key_restricted"),
    ("gemini", "gemini_location", "provider_rejected"),
])
def test_verify_reports_the_real_cause(provider, name, code):
    with pytest.raises(ProviderError) as caught:
        verify_key(provider, KEY, FakeTransport(GOOGLE_ERRORS[name]))
    assert caught.value.code == code


@pytest.mark.parametrize(("name", "expected"), [
    ("gemini_service_disabled", "provider=gemini http=403 status=PERMISSION_DENIED reason=SERVICE_DISABLED"),
    ("gemini_per_day", "provider=gemini http=429 status=RESOURCE_EXHAUSTED "
                       "reason=GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
    ("cloud_daily_limit", "provider=gemini http=403 status=- reason=dailyLimitExceeded"),
    ("gemini_model_not_found", "provider=gemini http=404 status=NOT_FOUND reason=-"),
])
def test_errors_carry_a_sanitised_diagnostic_line(name, expected):
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", ["x"], transport=FakeTransport(GOOGLE_ERRORS[name]), sleep=NO_SLEEP)
    line = caught.value.diagnostic("gemini", secret=KEY)
    assert line == expected
    assert KEY not in line and "project" not in line and "\n" not in line  # không key, không thân lỗi


def test_diagnostic_never_contains_the_key_even_if_google_echoed_it():
    body = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": KEY, "domain": "googleapis.com"}]}}
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", ["x"], transport=FakeTransport((400, body)), sleep=NO_SLEEP)
    line = caught.value.diagnostic("gemini", secret=KEY)
    assert KEY not in line and line.startswith("provider=gemini http=400 status=INVALID_ARGUMENT reason=")


def test_network_errors_have_a_diagnostic_line_too():
    transport = FakeTransport(handler=lambda *a: ProviderError("provider_unavailable", "ReadTimeout"))
    with pytest.raises(ProviderError) as caught:
        translate_segments("google_cloud", KEY, "", "vi", ["x"], transport=transport, sleep=NO_SLEEP)
    assert caught.value.diagnostic("google_cloud") == "provider=google_cloud http=- status=- reason=ReadTimeout"


@pytest.mark.parametrize("reply", [(500, {}), GOOGLE_ERRORS["gemini_overloaded"], ProviderError("provider_unavailable", "ReadTimeout")])
def test_verify_other_failures_are_provider_unavailable(reply):
    with pytest.raises(ProviderError) as caught:
        verify_key("gemini", KEY, FakeTransport(reply))
    assert caught.value.code == "provider_unavailable"


def test_batches_respect_segment_and_char_limits():
    short = [f"đoạn {index}" for index in range(BATCH_SEGMENTS + 1)]
    assert [len(batch) for batch in make_batches(short)] == [BATCH_SEGMENTS, 1]
    long = ["x" * 5000, "y" * 5000, "z" * 9000, "w"]
    assert [len(batch) for batch in make_batches(long)] == [1, 1, 1, 1]  # 5000+5000 > 8000; 9000 đứng một mình
    assert make_batches([]) == []


def test_tags_must_match_in_order_and_style_tags_must_balance():
    assert tags_match("Giá trị <b0></b0> của x", "The value <b0></b0> of x")
    assert not tags_match("<b0></b0> và <b1></b1>", "<b1></b1> and <b0></b0>")
    assert not tags_match("a <b0></b0>", "a")
    assert not tags_match("a", "a <b0></b0>")
    assert tags_match("<s1>Định lý</s1> 1", "<s1>Theorem</s1> 1")
    assert not tags_match("<s1>Định lý</s1> 1", "Theorem 1")
    assert not tags_match("<s1>a</s1>", "<s1>a")


def test_gemini_translates_in_parallel_batches_and_reports_progress():
    segments = [f"đoạn {index}" for index in range(100)]
    transport = FakeTransport(handler=gemini_echo())
    progress = []
    table = translate_segments("gemini", KEY, "gemini-3.5-flash-lite", "vi", segments, transport=transport,
                               on_progress=lambda done, total: progress.append((done, total)))
    assert table == {text: "VI " + text for text in segments}
    assert len(transport.calls) == 3 and progress[0] == (0, 100) and progress[-1] == (100, 100)
    call = transport.calls[0]
    assert call["url"] == f"{GEMINI_BASE}/models/gemini-3.5-flash-lite:generateContent"
    assert call["headers"]["x-goog-api-key"] == KEY and all(KEY not in c["url"] for c in transport.calls)
    body = call["json"]
    assert body["generationConfig"] == {  # gemini-3*: không temperature, không thinkingConfig
        "responseMimeType": "application/json", "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
    }
    prompt = body["systemInstruction"]["parts"][0]["text"]
    assert "Vietnamese" in prompt and "<b0>" in prompt and "same length" in prompt


@pytest.mark.parametrize(("model", "temperature"), [
    ("gemini-3.5-flash-lite", None), ("gemini-3.8-flash", None), ("gemini-3.1-pro-preview", None),
    ("gemini-2.5-flash", 0.2), ("gemini-4-exp", 0.2),
])
def test_gemini_3_models_get_no_temperature_and_nobody_gets_a_thinking_config(model, temperature):
    transport = FakeTransport(handler=gemini_echo())
    translate_segments("gemini", KEY, model, "vi", ["a"], transport=transport, sleep=NO_SLEEP)
    config = transport.calls[0]["json"]["generationConfig"]
    assert config.get("temperature") == temperature and ("temperature" in config) == (temperature is not None)
    assert "thinkingConfig" not in config


def test_gemini_reads_every_text_part_that_is_not_a_thought():
    reply = {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
        {"text": "Translating two segments...", "thought": True},
        {"text": '["VI a", '},
        {"text": '"VI b"]'},
    ]}}]}
    table = translate_segments("gemini", KEY, "gemini-3.5-flash", "vi", ["a", "b"], transport=FakeTransport((200, reply)),
                               sleep=NO_SLEEP)
    assert table == {"a": "VI a", "b": "VI b"}


def test_an_unparsable_gemini_reply_logs_the_finish_reason_and_batch_size_but_no_text():
    truncated = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '["VI bí mật'}]}}]}
    lines = []
    table = translate_segments("gemini", KEY, "m", "vi", ["bí mật a", "bí mật b"], transport=FakeTransport(handler=lambda *a: (200, truncated)),
                               sleep=NO_SLEEP, log=lines.append)
    assert table == {}
    assert lines == [
        "provider=gemini reply=unparsable finishReason=MAX_TOKENS batch=2 items=-",
        "provider=gemini reply=unparsable finishReason=MAX_TOKENS batch=1 items=-",
        "provider=gemini reply=unparsable finishReason=MAX_TOKENS batch=1 items=-",
    ]
    assert not any("bí mật" in line or KEY in line for line in lines)


def test_a_wrong_length_or_blocked_gemini_reply_is_logged_too():
    lines = []
    wrong = gemini_reply(["VI a"])  # 1 phần tử cho lô 2 đoạn
    blocked = {"promptFeedback": {"blockReason": "SAFETY"}}
    replies = [(200, wrong), (200, blocked), (200, gemini_reply(["VI b"]))]
    table = translate_segments("gemini", KEY, "m", "vi", ["a", "b"], transport=FakeTransport(*replies),
                               sleep=NO_SLEEP, log=lines.append)
    assert table == {"b": "VI b"}
    assert lines == ["provider=gemini reply=unparsable finishReason=- batch=2 items=1",
                     "provider=gemini reply=unparsable finishReason=blocked:SAFETY batch=1 items=-"]


def test_gemini_wrong_length_splits_the_batch_and_drops_the_last_bad_segment():
    def handler(method, url, headers, payload):
        asked = gemini_segments(payload)
        # Mọi lô chứa "c" trả thiếu một phần tử → chia đôi tới khi "c" đứng một mình rồi bị bỏ.
        return 200, gemini_reply(["VI " + text for text in asked if text != "c"])

    table = translate_segments("gemini", KEY, "m", "vi", ["a", "b", "c", "d"], transport=FakeTransport(handler=handler))
    assert table == {"a": "VI a", "b": "VI b", "d": "VI d"}


def test_gemini_malformed_json_is_treated_like_a_wrong_length():
    transport = FakeTransport((200, {"candidates": [{"content": {"parts": [{"text": "không phải JSON"}]}}]}))
    assert translate_segments("gemini", KEY, "m", "vi", ["một"], transport=transport) == {}


def test_translations_that_break_tags_are_dropped():
    handler = gemini_echo(lambda text: text.replace("<b0></b0>", "") if "công thức" in text else "VI " + text)
    table = translate_segments("gemini", KEY, "m", "vi", ["công thức <b0></b0>", "chữ"], transport=FakeTransport(handler=handler))
    assert table == {"chữ": "VI chữ"}


def test_retries_429_and_5xx_with_backoff_then_succeeds():
    calls = {"n": 0}

    def handler(method, url, headers, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return 429, {"error": {"status": "RESOURCE_EXHAUSTED"}}
        if calls["n"] == 2:
            return 503, {}
        return 200, gemini_reply(["VI " + text for text in gemini_segments(payload)])

    slept = []
    table = translate_segments("gemini", KEY, "m", "vi", ["x"], transport=FakeTransport(handler=handler), sleep=slept.append)
    assert table == {"x": "VI x"} and slept == [BACKOFF[0], BACKOFF[1]]


def test_rate_limits_get_six_attempts_with_the_usual_backoff_then_rate_limited():
    """429 không kèm hạn mức NGÀY là giới hạn tốc độ (thử lại được), không phải "hết hạn mức"."""
    slept = []
    transport = FakeTransport(handler=lambda *a: (429, {}))
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", ["x"], transport=transport, sleep=slept.append)
    assert caught.value.code == "rate_limited"
    assert len(transport.calls) == 6 and slept == [2, 4, 8, 16, 16]


@pytest.mark.parametrize(("reply", "wait"), [
    (GOOGLE_ERRORS["gemini_per_minute"], 13),  # RetryInfo.retryDelay "13s"
    ((429, {}, {"Retry-After": "7"}), 7),  # header Retry-After (giây)
    ((429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "300s"}]}}), 60),  # trần 60 s
    (GOOGLE_ERRORS["cloud_user_rate_limit"], 2),  # 403 userRateLimitExceeded: không gợi ý → backoff thường
])
def test_rate_limit_waits_what_google_asks_capped_at_a_minute(reply, wait):
    calls = []

    def handler(method, url, headers, payload):
        calls.append(1)
        return reply if len(calls) == 1 else (200, cloud_reply(["VI x"]) if "translation" in url else gemini_reply(["VI x"]))

    slept = []
    provider = "google_cloud" if reply is GOOGLE_ERRORS["cloud_user_rate_limit"] else "gemini"
    table = translate_segments(provider, KEY, "m", "vi", ["x"], transport=FakeTransport(handler=handler), sleep=slept.append)
    assert table == {"x": "VI x"} and slept == [wait]


def test_after_the_first_rate_limit_the_rest_of_the_job_runs_one_request_at_a_time(monkeypatch):
    from app.providers import client as module

    gates = []

    class SpyGate(module._Gate):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.entered = 0
            gates.append(self)

        def slot(self):
            self.entered += 1
            return super().slot()

    monkeypatch.setattr(module, "_Gate", SpyGate)
    first = {"done": False}

    def handler(method, url, headers, payload):
        if not first["done"]:
            first["done"] = True
            return GOOGLE_ERRORS["gemini_per_minute"]
        return 200, gemini_reply(["VI " + text for text in gemini_segments(payload)])

    limits_while_waiting = []
    segments = [f"đoạn {index}" for index in range(200)]  # 5 lô
    transport = FakeTransport(handler=handler)
    table = translate_segments("gemini", KEY, "m", "vi", segments, transport=transport,
                               sleep=lambda seconds: limits_while_waiting.append(gates[0].limit))
    assert table == {text: "VI " + text for text in segments}
    [gate] = gates
    assert limits_while_waiting == [1]  # hạ về 1 NGAY khi bị giới hạn, trước cả lần chờ
    assert gate.limit == 1 and gate.entered == len(transport.calls) == 6  # mọi request đều qua cổng


def test_gate_lets_only_one_request_through_once_narrowed():
    import threading

    from app.providers.client import _Gate

    gate = _Gate(4, threading.Event())
    held = gate.slot()
    held.__enter__()
    gate.narrow()
    entered = threading.Event()

    def second():
        with gate.slot():
            entered.set()

    worker = threading.Thread(target=second)
    worker.start()
    with gate.changed:  # chờ (không ngủ) tới khi luồng thứ hai đứng đợi ở cổng
        assert gate.changed.wait_for(lambda: gate.waiting == 1, timeout=5)
    assert not entered.is_set()  # request đầu chưa xong: request thứ hai chưa được đi
    held.__exit__(None, None, None)
    worker.join(5)
    assert entered.is_set() and gate.active == 0


def test_abort_wakes_requests_waiting_at_the_gate():
    import threading

    from app.providers.client import _Gate

    abort = threading.Event()
    gate = _Gate(1, abort)
    held = gate.slot()
    held.__enter__()
    outcome = []

    def second():
        try:
            with gate.slot():
                outcome.append("entered")
        except ProviderError as error:
            outcome.append(error.detail)

    worker = threading.Thread(target=second)
    worker.start()
    with gate.changed:
        assert gate.changed.wait_for(lambda: gate.waiting == 1, timeout=5)
    gate.stop()
    worker.join(5)
    assert outcome == ["aborted"] and abort.is_set()
    held.__exit__(None, None, None)


def test_finished_batches_are_handed_over_even_when_another_batch_fails(monkeypatch):
    """Lô đã dịch xong (đã trả tiền) phải tới tay người gọi qua on_batch dù lô khác hỏng chết người."""
    monkeypatch.setattr("app.providers.client.PARALLEL", 1)  # thứ tự lô xác định
    segments = ["a" * 5000, "b" * 5000, "c" * 5000]  # 3 lô (5000 + 5000 > 8000)

    def handler(method, url, headers, payload):
        [text] = gemini_segments(payload)
        return GOOGLE_ERRORS["gemini_key_invalid"] if text.startswith("c") else (200, gemini_reply(["VI " + text]))

    handed = []
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", segments, transport=FakeTransport(handler=handler), sleep=NO_SLEEP,
                           on_batch=handed.append)
    assert caught.value.code == "invalid_api_key"
    assert handed == [{"a" * 5000: "VI " + "a" * 5000}, {"b" * 5000: "VI " + "b" * 5000}]


def test_exhausted_5xx_is_provider_unavailable():
    with pytest.raises(ProviderError) as caught:
        translate_segments("google_cloud", KEY, "", "vi", ["x"], transport=FakeTransport(handler=lambda *a: (502, {})), sleep=NO_SLEEP)
    assert caught.value.code == "provider_unavailable"


def test_rejected_key_mid_job_stops_everything():
    transport = FakeTransport(handler=lambda *a: GOOGLE_ERRORS["gemini_key_invalid"])
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", [f"đoạn {index}" for index in range(200)], transport=transport, sleep=NO_SLEEP)
    assert caught.value.code == "invalid_api_key"
    assert len(transport.calls) <= 5  # 5 lô; lỗi chết người không được khiến các lô còn lại cứ gọi tiếp


def test_translate_requests_get_the_long_translate_timeout_and_key_checks_stay_short():
    """generateContent không stream chỉ trả lời khi dịch xong cả lô — 15 s của bước kiểm key là quá ngắn."""
    gemini = FakeTransport(handler=gemini_echo())
    translate_segments("gemini", KEY, "m", "vi", ["a"], transport=gemini, sleep=NO_SLEEP)
    cloud = FakeTransport((200, cloud_reply(["b"])))
    translate_segments("google_cloud", KEY, "", "vi", ["a"], transport=cloud, sleep=NO_SLEEP)
    assert gemini.calls[0]["timeout"] == (10, 120) and cloud.calls[0]["timeout"] == (10, 120)
    probe = FakeTransport((200, GEMINI_MODELS_BODY), (200, cloud_reply(["ok"])))
    verify_key("gemini", KEY, probe)
    verify_key("google_cloud", KEY, probe)
    assert [call["timeout"] for call in probe.calls] == [15, 15]


def test_a_read_timeout_on_a_translate_request_is_retried_once_then_gives_up():
    """Hết giờ đọc = có thể Google vẫn đang dịch (và tính tiền) lô đó: thử lại đúng một lần, không phải 4."""
    transport = FakeTransport(handler=lambda *a: ProviderError("provider_unavailable", "ReadTimeout"))
    slept = []
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", ["x"], transport=transport, sleep=slept.append)
    assert caught.value.code == "provider_unavailable"
    assert len(transport.calls) == 2 and slept == [BACKOFF[0]]


class FakeClock:
    """Đồng hồ giả: `sleep` và mỗi request (handler gọi `spend`) đẩy thời gian lên — không ngủ thật."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def spend(self, seconds: float) -> None:
        self.now += seconds


def test_retries_stop_once_the_per_request_budget_is_spent():
    """Mỗi lần thử có thể mất tới 10+120 s: không bắt đầu lần thử mới quá RETRY_BUDGET, để một lô
    xấu nhất vẫn xong (hoặc hỏng) trước khi runner coi job là đứng (JOB_STALL 8 phút)."""
    from app.providers.client import RETRY_BUDGET, TRANSLATE_TIMEOUT

    clock = FakeClock()

    def slow_504(*args):
        clock.spend(100)  # 504 sau 100 s xử lý
        return 504, {"error": {"status": "DEADLINE_EXCEEDED"}}

    transport = FakeTransport(handler=slow_504)
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", ["x"], transport=transport, sleep=clock.spend, clock=clock)
    assert caught.value.code == "provider_unavailable"
    assert len(transport.calls) == 2  # t=0→100, chờ 2 s, t=102→202; lần 3 sẽ bắt đầu sau 180 s → dừng
    worst_case = RETRY_BUDGET + sum(TRANSLATE_TIMEOUT)
    assert clock.now <= worst_case < 8 * 60 * 0.7


def test_other_network_errors_keep_the_normal_backoff():
    transport = FakeTransport(handler=lambda *a: ProviderError("provider_unavailable", "ConnectionError"))
    slept = []
    with pytest.raises(ProviderError) as caught:
        translate_segments("gemini", KEY, "m", "vi", ["x"], transport=transport, sleep=slept.append)
    assert caught.value.code == "provider_unavailable"
    assert len(transport.calls) == len(BACKOFF) + 1 and slept == list(BACKOFF)


def test_cloud_escapes_html_outside_the_tags_it_must_keep():
    """format=html: "a < b & c" gửi nguyên văn thì Google hiểu "<" là thẻ HTML và nuốt/sửa chữ — phải
    escape &, <, > ngoài các thẻ <bN>/</bN>/<sN>/</sN> của lõi; bước unescape sẵn có trả lại nguyên dạng."""
    source = "a < b & c <b0></b0> và <s1>x > y</s1>"
    sent = []

    def handler(method, url, headers, payload):
        sent.extend(payload["q"])
        return 200, cloud_reply([text.replace("và", "and") for text in payload["q"]])  # Google trả lại HTML

    table = translate_segments("google_cloud", KEY, "", "vi", [source], transport=FakeTransport(handler=handler), sleep=NO_SLEEP)
    assert sent == ["a &lt; b &amp; c <b0></b0> và <s1>x &gt; y</s1>"]
    assert table == {source: "a < b & c <b0></b0> and <s1>x > y</s1>"}


def test_cloud_translates_as_html_and_unescapes_entities():
    def handler(method, url, headers, payload):
        assert payload == {"q": ["x"], "target": "vi", "format": "html"} and headers["X-Goog-Api-Key"] == KEY
        return 200, cloud_reply(["&quot;x&quot; &amp; y"])

    table = translate_segments("google_cloud", KEY, "", "vi", ["x"], transport=FakeTransport(handler=handler))
    assert table == {"x": '"x" & y'}


def test_style_instructions_follow_the_system_prompt_and_only_for_gemini():
    transport = FakeTransport(handler=gemini_echo())
    translate_segments("gemini", KEY, "gemini-3.5-flash-lite", "vi", ["xin chào"], transport=transport,
                       instructions="Style requirements…\n- Tone: warm and conversational.")
    prompt = transport.calls[0]["json"]["systemInstruction"]["parts"][0]["text"]
    assert prompt == SYSTEM_PROMPT.format(language="Vietnamese") + "\n\nStyle requirements…\n- Tone: warm and conversational."
    bare = FakeTransport(handler=gemini_echo())
    translate_segments("gemini", KEY, "gemini-3.5-flash-lite", "vi", ["xin chào"], transport=bare)
    assert bare.calls[0]["json"]["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT.format(language="Vietnamese")  # y như cũ
    cloud = FakeTransport((200, cloud_reply(["hello"])))
    translate_segments("google_cloud", KEY, "", "vi", ["xin chào"], transport=cloud, instructions="- Tone: warm.")
    assert "Tone" not in json.dumps(cloud.calls[0]["json"])  # Cloud Translation không nhận prompt


def test_braces_in_the_user_text_of_the_instructions_reach_gemini_untouched():
    """Chỉ dẫn chứa văn bản tự do của người dùng: KHÔNG được đi qua str.format (KeyError/IndexError/ValueError,
    hoặc bị thay {language}) — chỉ SYSTEM_PROMPT được format, chỉ dẫn nối nguyên văn phía sau."""
    instructions = "Style requirements…\n- Additional instructions from the user (about style only): «{language} {} {0} {x!r} }{ {{»"
    transport = FakeTransport(handler=gemini_echo())
    table = translate_segments("gemini", KEY, "gemini-3.5-flash-lite", "vi", ["xin chào"], transport=transport,
                               instructions=instructions)
    assert table == {"xin chào": "VI xin chào"}
    prompt = transport.calls[0]["json"]["systemInstruction"]["parts"][0]["text"]
    assert prompt == SYSTEM_PROMPT.format(language="Vietnamese") + "\n\n" + instructions
    empty = FakeTransport(handler=gemini_echo())
    translate_segments("gemini", KEY, "gemini-3.5-flash-lite", "vi", ["xin chào"], transport=empty, instructions="")
    bare = FakeTransport(handler=gemini_echo())
    translate_segments("gemini", KEY, "gemini-3.5-flash-lite", "vi", ["xin chào"], transport=bare)
    assert empty.calls[0]["json"] == bare.calls[0]["json"]  # chỉ dẫn rỗng = request y hệt hôm nay
