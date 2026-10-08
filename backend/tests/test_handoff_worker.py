import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.engine import fonts
from app.engine.fonts import FontProfileError
from app.engine.handoff_worker import ERROR_MESSAGES, main, run
from app.providers.client import ProviderError, translate_segments
from helpers import GOOGLE_ERRORS, PDF, FakeTransport, gemini_echo, gemini_reply, gemini_segments

SEGMENTS = ["Xin chào <b0></b0>", "Tạm biệt", "Xin chào <b0></b0>"]  # có trùng: worker phải khử trùng


@dataclass
class Result:
    path: Path
    untranslated: int


def fake_core(calls: list, *, untranslated: int = 2, fail_pass: int | None = None, texts: list[str] = SEGMENTS):
    """translate_pdf giả: lượt 1 (emit_segments) ghi các đoạn chưa dịch; lượt 2 (segments) đọc bảng và dựng PDF."""

    def translate_pdf(source, output_dir, *, target_language, overwrite, engine, segments=None, emit_segments=None,
                      on_progress=None):
        calls.append({"engine": engine, "segments": segments, "emit_segments": emit_segments, "output_dir": Path(output_dir)})
        if fail_pass == len(calls):
            raise RuntimeError("No text could be extracted from doc.pdf: the selected pages are image-only scans.")
        assert engine == "handoff" and overwrite is True and target_language == "vi"
        on_progress(1, 2)
        on_progress(2, 2)
        output = Path(output_dir) / f"{Path(source).stem}-{target_language}.pdf"
        if emit_segments is not None:
            Path(emit_segments).write_text(
                "".join(json.dumps({"src": text}, ensure_ascii=False) + "\n" for text in texts), encoding="utf-8")
            output.write_bytes(PDF)  # lượt 1 cũng sinh một PDF (chưa dịch) — phải bị bỏ
            return Result(output, 0)
        calls[-1]["table"] = [json.loads(line) for line in Path(segments).read_text(encoding="utf-8").splitlines() if line]
        output.write_bytes(PDF + b"translated")
        return Result(output, untranslated)

    return translate_pdf


def fake_provider(seen: list, table: dict | None = None, error: str | None = None):
    def translate(provider, api_key, model, language, segments, on_progress, on_batch=None):
        seen.append({"provider": provider, "api_key": api_key, "model": model, "language": language, "segments": list(segments)})
        if error:
            raise ProviderError(error)
        on_progress(0, len(segments))
        on_progress(len(segments), len(segments))
        return {src: dst for src, dst in (table or {}).items() if src in segments}

    return translate


@pytest.fixture
def job(tmp_path):
    source = tmp_path / "doc.pdf"
    source.write_bytes(PDF)
    return source, tmp_path


def test_two_passes_translate_and_count_untranslated(job):
    source, out = job
    calls, seen, emitted = [], [], []
    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="gemini-3.5-flash-lite",
               translate_pdf=fake_core(calls), translate=fake_provider(seen, {"Xin chào <b0></b0>": "Hello <b0></b0>"}),
               emit=emitted.append)
    assert code == 0
    assert [c["engine"] for c in calls] == ["handoff", "handoff"]
    assert calls[0]["emit_segments"] == out / "segments-out.jsonl" and calls[0]["segments"] is None
    assert calls[0]["output_dir"] != out and calls[0]["output_dir"].parent == out  # lượt 1 ghi vào thư mục tạm
    assert calls[1]["segments"] == out / "segments.jsonl" and calls[1]["emit_segments"] is None and calls[1]["output_dir"] == out
    assert calls[1]["table"] == [{"src": "Xin chào <b0></b0>", "dst": "Hello <b0></b0>"}]
    [call] = seen
    assert call == {"provider": "gemini", "api_key": "AIza-x", "model": "gemini-3.5-flash-lite", "language": "vi",
                    "segments": ["Xin chào <b0></b0>", "Tạm biệt"]}
    stages = [(line["stage"], line["p"], line["t"]) for line in emitted if "stage" in line]
    # Dòng (stage, 0, 0) đầu mỗi bước là của worker (runner đổi thông điệp ngay); các dòng sau theo callback.
    assert stages == [("split", 0, 0), ("split", 1, 2), ("split", 2, 2),
                      ("translate", 0, 0), ("translate", 0, 2), ("translate", 2, 2),
                      ("render", 0, 0), ("render", 1, 2), ("render", 2, 2)]
    final = emitted[-1]
    assert final == {"ok": True, "output": str(out / "doc-vi.pdf"), "untranslated": 3}  # 2 của lõi + 1 provider bỏ
    assert (out / "doc-vi.pdf").read_bytes().endswith(b"translated")
    assert not list(out.glob("pass1-*"))  # thư mục tạm của lượt 1 đã dọn
    assert "AIza-x" not in json.dumps(emitted)


def test_provider_error_becomes_a_coded_failure(job):
    source, out = job
    calls, emitted = [], []
    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=fake_core(calls),
               translate=fake_provider([], error="invalid_api_key"), emit=emitted.append)
    assert code == 1 and len(calls) == 1
    assert emitted[-1] == {"ok": False, "error": ERROR_MESSAGES["invalid_api_key"], "code": "invalid_api_key"}
    assert not (out / "doc-vi.pdf").exists()
    assert (out / "segments.jsonl").read_text(encoding="utf-8") == ""  # bảng (rỗng) giữ lại cho lần Dịch lại


PROVIDER_CODES = ["invalid_api_key", "api_not_enabled", "billing_disabled", "key_restricted", "rate_limited",
                  "quota_exceeded", "model_unavailable", "provider_rejected", "provider_unavailable"]


@pytest.mark.parametrize("code", PROVIDER_CODES)
def test_every_provider_error_code_has_its_own_message(job, code):
    source, out = job
    emitted = []
    assert run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=fake_core([]),
               translate=fake_provider([], error=code), emit=emitted.append, diagnose=lambda line: None) == 1
    assert emitted[-1] == {"ok": False, "error": ERROR_MESSAGES[code], "code": code}
    assert len({ERROR_MESSAGES[c] for c in PROVIDER_CODES}) == len(PROVIDER_CODES)  # không mã nào dùng chung câu


def test_model_unavailable_tells_the_user_what_to_do():
    assert ERROR_MESSAGES["model_unavailable"] == "Model này không còn dùng được. Tải tệp lên lại và chọn model khác."


def test_a_real_google_error_becomes_one_sanitised_stderr_line_and_a_coded_failure(job, capsys):
    """Đi qua translate_segments thật + FakeTransport: dòng chẩn đoán có mã của Google, không có thân lỗi/key."""
    source, out = job
    key = "AIza-real-looking-key-0042"
    transport = FakeTransport(GOOGLE_ERRORS["gemini_service_disabled"])

    def translate(provider, api_key, model, language, segments, on_progress, on_batch=None):
        return translate_segments(provider, api_key, model, language, segments, transport=transport,
                                  on_progress=on_progress, sleep=lambda seconds: None)

    emitted = []
    code = run(source, out, "vi", provider="gemini", api_key=key, model="gemini-3.5-flash-lite",
               translate_pdf=fake_core([]), translate=translate, emit=emitted.append)
    err = capsys.readouterr().err
    assert code == 1 and emitted[-1]["code"] == "api_not_enabled"
    assert err.splitlines() == ["provider=gemini http=403 status=PERMISSION_DENIED reason=SERVICE_DISABLED"]
    assert key not in err and key not in json.dumps(emitted) and "project" not in err


LONG = ["a" * 5000, "b" * 5000, "c" * 5000]  # 3 lô (5000 + 5000 > BATCH_CHARS)
META = {"provider": "gemini", "model": "gemini-3.5-flash-lite", "target_language": "vi"}


def real_translate(transport):
    """translate_segments thật trên FakeTransport — không mạng, không ngủ."""

    def translate(provider, api_key, model, language, segments, on_progress, on_batch=None):
        return translate_segments(provider, api_key, model, language, segments, transport=transport,
                                  on_progress=on_progress, on_batch=on_batch, sleep=lambda seconds: None)

    return translate


def fail_on_c(method, url, headers, payload):
    [text] = gemini_segments(payload)
    return GOOGLE_ERRORS["gemini_per_day"] if text.startswith("c") else (200, gemini_reply(["VI " + text]))


def run_long(out, source, transport, *, model="gemini-3.5-flash-lite", calls=None, emitted=None):
    return run(source, out, "vi", provider="gemini", api_key="AIza-x", model=model,
               translate_pdf=fake_core(calls if calls is not None else [], texts=LONG), translate=real_translate(transport),
               emit=(emitted if emitted is not None else []).append, diagnose=lambda line: None)


def table_on_disk(out) -> dict:
    lines = (out / "segments.jsonl").read_text(encoding="utf-8").splitlines()
    return {record["src"]: record["dst"] for record in map(json.loads, lines)}


def test_a_job_that_fails_midway_keeps_the_paid_part_and_a_rerun_translates_only_the_rest(job, monkeypatch):
    monkeypatch.setattr("app.providers.client.PARALLEL", 1)  # thứ tự lô xác định
    source, out = job
    first = FakeTransport(handler=fail_on_c)
    assert run_long(out, source, first) == 1
    assert table_on_disk(out) == {"a" * 5000: "VI " + "a" * 5000, "b" * 5000: "VI " + "b" * 5000}  # 2 lô đã trả tiền
    assert json.loads((out / "segments.meta.json").read_text(encoding="utf-8")) == META

    second = FakeTransport(handler=gemini_echo())
    calls, emitted = [], []
    assert run_long(out, source, second, calls=calls, emitted=emitted) == 0
    assert [gemini_segments(call["json"]) for call in second.calls] == [["c" * 5000]]  # chỉ phần còn thiếu
    assert {row["src"] for row in calls[1]["table"]} == set(LONG)  # lượt 2 nhận đủ bảng
    assert [(line["p"], line["t"]) for line in emitted if line.get("stage") == "translate"] == [(0, 0), (2, 3), (3, 3)]
    assert emitted[-1]["ok"] is True and emitted[-1]["untranslated"] == 2  # 2 của lõi giả, provider dịch đủ


def test_a_different_model_ignores_the_previous_table(job, monkeypatch):
    monkeypatch.setattr("app.providers.client.PARALLEL", 1)
    source, out = job
    assert run_long(out, source, FakeTransport(handler=fail_on_c)) == 1
    second = FakeTransport(handler=gemini_echo())
    assert run_long(out, source, second, model="gemini-3.8-flash") == 0
    assert len(second.calls) == 3  # bảng cũ của model khác không được dùng lại
    assert json.loads((out / "segments.meta.json").read_text(encoding="utf-8"))["model"] == "gemini-3.8-flash"
    assert table_on_disk(out) == {text: "VI " + text for text in LONG}


def test_a_torn_last_line_from_a_killed_worker_is_dropped_on_resume(job):
    source, out = job
    (out / "segments.meta.json").write_text(json.dumps(META), encoding="utf-8")
    good = json.dumps({"src": "a" * 5000, "dst": "VI " + "a" * 5000}) + "\n"
    (out / "segments.jsonl").write_text(good + '{"src": "bbbb', encoding="utf-8")  # bị giết giữa lúc ghi
    transport = FakeTransport(handler=gemini_echo())
    assert run_long(out, source, transport) == 0  # lõi giả json.loads từng dòng: dòng dở dang sẽ làm nó hỏng
    assert len(transport.calls) == 2
    assert table_on_disk(out) == {text: "VI " + text for text in LONG}


def test_no_segments_skips_the_provider_but_still_renders(job):
    source, out = job
    seen, emitted = [], []

    def core(src, output_dir, *, target_language, overwrite, engine, segments=None, emit_segments=None, on_progress=None):
        output = Path(output_dir) / f"{Path(src).stem}-{target_language}.pdf"
        output.write_bytes(PDF)
        if emit_segments is not None:
            Path(emit_segments).write_text("", encoding="utf-8")  # lõi tự có hết bản dịch (vd từ cache)
        else:
            assert Path(segments).read_text(encoding="utf-8") == ""  # lượt 2 vẫn cần tệp bảng (rỗng) tồn tại
        return Result(output, 0)

    code = run(source, out, "vi", provider="google_cloud", api_key="k" * 12, model="", translate_pdf=core,
               translate=fake_provider(seen), emit=emitted.append)
    assert code == 0 and seen == []
    assert emitted[-1] == {"ok": True, "output": str(out / "doc-vi.pdf"), "untranslated": 0}
    assert [line["stage"] for line in emitted if "stage" in line] == ["split", "render"]


def test_core_failure_is_translated_to_a_friendly_message(job):
    source, out = job
    emitted = []
    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=fake_core([], fail_pass=1),
               translate=fake_provider([]), emit=emitted.append)
    assert code == 1 and emitted[-1]["ok"] is False and "bản scan" in emitted[-1]["error"]


def test_main_requires_provider_and_key_in_the_environment(job, monkeypatch, capsys):
    source, out = job
    monkeypatch.setattr("sys.argv", ["handoff_worker.py", str(source), str(out), "vi"])
    for name in ("TRANSLATE_PROVIDER", "TRANSLATE_API_KEY", "TRANSLATE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert main() == 2
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["ok"] is False and "TRANSLATE_PROVIDER" in line["error"]


def test_the_font_profile_is_prepared_and_announced_before_the_split_pass(job):
    source, out = job
    calls, emitted, order = [], [], []
    core = fake_core(calls)

    def recording_core(*args, **kwargs):
        order.append("core")
        return core(*args, **kwargs)

    def prepare(choice, src, emit):
        order.append(("prepare", choice, src))
        emit({"font": "serif"})
        return "serif"

    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=recording_core,
               translate=fake_provider([]), emit=emitted.append, font="auto", prepare=prepare)
    assert code == 0
    assert order == [("prepare", "auto", source), "core", "core"]
    assert emitted[0] == {"font": "serif"}  # trước mọi dòng tiến độ
    assert sum(1 for line in emitted if "font" in line) == 1


def test_a_font_profile_error_becomes_a_coded_failure_before_the_core_runs(job):
    source, out = job
    calls, emitted, diagnostics = [], [], []

    def prepare(choice, src, emit):
        raise FontProfileError("font_profile_unsupported", "hook:output_style_font_paths:not-callable")

    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=fake_core(calls),
               translate=fake_provider([]), emit=emitted.append, diagnose=diagnostics.append, prepare=prepare)
    assert code == 1 and calls == []
    assert emitted == [{"ok": False, "error": ERROR_MESSAGES["font_profile_unsupported"], "code": "font_profile_unsupported"}]
    assert diagnostics == ["font_profile code=font_profile_unsupported detail=hook:output_style_font_paths:not-callable"]


def test_any_other_font_step_error_is_the_same_coded_failure_without_the_raw_message(job):
    source, out = job
    calls, emitted, diagnostics = [], [], []

    def prepare(choice, src, emit):
        raise PermissionError(13, "Permission denied", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")

    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=fake_core(calls),
               translate=fake_provider([]), emit=emitted.append, diagnose=diagnostics.append, prepare=prepare)
    assert code == 1 and calls == []
    assert emitted == [{"ok": False, "error": ERROR_MESSAGES["font_profile_unsupported"], "code": "font_profile_unsupported"}]
    assert diagnostics == ["font_profile code=font_profile_unsupported detail=error:PermissionError"]


def test_the_rendered_pdf_is_handed_to_subset_before_reporting_done(job):
    source, out = job
    emitted, subset = [], []
    code = run(source, out, "vi", provider="gemini", api_key="AIza-x", model="m", translate_pdf=fake_core([]),
               translate=fake_provider([]), emit=emitted.append, subset=lambda path: subset.append(path))
    assert code == 0 and subset == [out / "doc-vi.pdf"]
    assert emitted[-1]["ok"] is True


def test_font_error_codes_have_their_own_messages():
    for code in ("font_profile_unsupported", "font_files_missing"):
        assert ERROR_MESSAGES[code] == fonts.ERROR_MESSAGES[code]
    assert ERROR_MESSAGES["font_files_missing"] == "Máy chủ thiếu tệp font của bản dịch. Báo quản trị viên."
