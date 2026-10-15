import json
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.db import make_engine, make_session_factory, upgrade_db, utcnow
from app.engine.handoff_worker import instructions_digest
from app.engine.jobs import MISSING_KEY_MESSAGE, NO_HANDOFF_WORKER_MESSAGE, RESTORE_SOURCE_MISSING_MESSAGE, JobRunner, Previous
from app.engine.paths import file_dir, safe_name
from app.files.service import download_target
from app.models import ApiCredential, File, FileVersion, User
from app.profiles.prompt import HEADER, build_instructions
from app.profiles.snapshot import load as load_snapshot
from app.providers.catalog import ENGINE_BY_ID
from app.providers.crypto import encrypt
from app.system.store import instance_row
from helpers import FAKE_HANDOFF_WORKER, FAKE_WORKER, PDF


@pytest.fixture
def factory(settings):
    settings.users_dir.mkdir(parents=True)
    upgrade_db(settings.database_url)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        db.add(User(id="u1", email="u1@example.com", password_hash="x", email_verified_at=utcnow()))
        db.commit()
    yield session_factory
    engine.dispose()


@pytest.fixture
def make_runner(factory, settings):
    runners = []

    def _make(**overrides) -> JobRunner:
        options = {"max_concurrent": 1, "stall_seconds": 5, "timeout_seconds": 30,
                   "lock_path": settings.data_dir / "runner.lock", "lock_retry_seconds": 0.2,
                   "handoff_worker_cmd": (sys.executable, str(FAKE_HANDOFF_WORKER)),
                   "secret_key": settings.secret_key} | overrides
        runner = JobRunner(factory, settings.users_dir, (sys.executable, str(FAKE_WORKER)), **options)
        runners.append(runner)
        return runner

    yield _make
    for runner in runners:
        runner.stop()


def add_file(factory, settings, filename="doc.pdf", status="queued", engine="google_free", model=None,
             font="auto", config=None) -> str:
    # Tệp nằm trên đĩa TRƯỚC khi có dòng trong DB — như create_file: runner tự quét DB nên
    # dòng "queued" xuất hiện là có thể bị nhận ngay.
    file_id = uuid.uuid4().hex[:12]
    directory = file_dir(settings.users_dir, "u1", file_id)
    directory.mkdir(parents=True)
    (directory / safe_name(filename)).write_bytes(PDF)
    with factory() as db:
        db.add(File(id=file_id, user_id="u1", filename=filename, search_name=filename.casefold(),
                    language="vi", status=status, engine=engine, model=model, font=font, config=config))
        db.commit()
    return file_id


def processed_by(runner) -> list[str]:
    """Ghi lại các job runner này THẬT SỰ chạy worker (chỉ xảy ra sau khi nhận việc thành công)."""
    ran: list[str] = []
    real = runner._run_worker

    def recording(file_id, *args):
        ran.append(file_id)
        return real(file_id, *args)

    runner._run_worker = recording
    return ran


def wait_row(factory, file_id, statuses=("done", "error"), timeout=15.0) -> File:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with factory() as db:
            row = db.get(File, file_id)
            if row is not None and row.status in statuses:
                return row
        time.sleep(0.05)
    raise AssertionError(f"{file_id} không tới trạng thái {statuses}")


def run_one(factory, settings, make_runner, filename, engine="google_free", model=None, font="auto",
            **runner_options) -> File:
    runner = make_runner(**runner_options)
    runner.start()
    file_id = add_file(factory, settings, filename, engine=engine, model=model, font=font)
    runner.enqueue(file_id)
    return wait_row(factory, file_id)


def add_credential(factory, settings, provider="gemini", key="AIza-test-key-0001", models="[]") -> None:
    with factory() as db:
        db.add(ApiCredential(id=f"c-{provider}"[:12], user_id="u1", provider=provider, hint=key[-4:], models=models,
                             secret=encrypt(settings.secret_key, "u1", provider, key), verified_at=utcnow()))
        db.commit()


def wait_stage(factory, file_id, stage, timeout=10.0) -> File:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with factory() as db:
            row = db.get(File, file_id)
            if row is not None and row.stage == stage:
                return row
        time.sleep(0.05)
    raise AssertionError(f"{file_id} không tới stage {stage}")


def wait_gone(path, timeout=10.0) -> None:
    """Việc dọn SAU commit của _finish_rebuild (spec 2026-10-14 §5 bước 6: rmtree kho đã tỉa → thay bảng đoạn → rmtree rebuild/)
    chạy sau khi dòng đã `done` — đợi rebuild/ (bước cuối) biến mất, có hạn, thay vì kiểm ngay lúc thấy `done`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} vẫn còn sau {timeout}s")


def test_safe_name_keeps_the_name_but_not_the_path():
    assert safe_name("../../evil.pdf") == "evil.pdf"
    assert safe_name("Báo cáo: quý 3?.pdf") == "Báo cáo_ quý 3_.pdf"


def test_successful_job_records_the_result(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "Báo cáo.pdf")
    assert row.status == "done", row.message
    assert row.output_name == "Báo cáo-vi.pdf"
    assert (file_dir(settings.users_dir, "u1", row.id) / row.output_name).is_file()
    assert (row.done_pages, row.total_pages, row.untranslated, row.message) == (2, 2, 0, "Xong")
    assert row.started_at is not None and row.finished_at is not None


def test_partial_translation_is_counted(factory, settings, make_runner):
    assert run_one(factory, settings, make_runner, "partial.pdf").untranslated == 3


def test_worker_error_message_is_kept(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "fail.pdf")
    assert row.status == "error" and "bản scan" in row.message


def test_crash_reports_the_stderr_tail(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "crash.pdf")
    assert row.status == "error"
    assert "dừng đột ngột" in row.message and "Segmentation fault" in row.message


def test_stalled_worker_is_killed(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "hang.pdf", stall_seconds=1)
    assert row.status == "error" and "không nhích thêm trang nào" in row.message
    assert "(đứng ở trang 0/2)" in row.message  # google_free: thông điệp cũ, tính theo trang
    assert (row.done_pages, row.total_pages) == (0, 2)


def test_stall_during_the_translate_step_counts_segments_not_pages(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    row = run_one(factory, settings, make_runner, "hang.pdf", engine="gemini", model="gemini-3.5-flash-lite", stall_seconds=1)
    assert row.status == "error"
    assert "không nhích thêm đoạn nào" in row.message and "(đứng ở đoạn 3/10)" in row.message
    assert "trang" not in row.message


def test_overlong_worker_is_killed(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "hang.pdf", stall_seconds=30, timeout_seconds=1)
    assert row.status == "error" and row.message.startswith("Quá")


def test_output_outside_the_job_folder_is_rejected(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "escape.pdf")
    assert row.status == "error" and "không tìm thấy tệp kết quả" in row.message
    assert row.output_name is None


def test_progress_is_visible_while_running(factory, settings, make_runner):
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "slow.pdf")
    runner.enqueue(file_id)
    deadline = time.monotonic() + 5
    while (progress := runner.progress(file_id)) is None or progress.total == 0:
        assert time.monotonic() < deadline, "không thấy tiến độ"
        time.sleep(0.05)
    assert (progress.done, progress.total) == (1, 2)
    wait_row(factory, file_id)
    assert runner.progress(file_id) is None


def test_deleted_queued_row_is_never_run(factory, settings, make_runner):
    runner = make_runner()
    ran = processed_by(runner)
    runner.start()
    first, second = add_file(factory, settings, "slow.pdf"), add_file(factory, settings, "doc.pdf")
    runner.enqueue(first)
    runner.enqueue(second)
    wait_row(factory, first, statuses=("running",))
    with factory() as db:  # như files.service.delete_file: xoá dòng queued là đủ
        db.execute(delete(File).where(File.id == second, File.status == "queued"))
        db.commit()
    wait_row(factory, first)
    time.sleep(1.5)  # hơn một chu kỳ quét DB
    assert ran == [first]
    assert not (file_dir(settings.users_dir, "u1", second) / "doc-vi.pdf").exists()


def test_queue_depth_counts_waiting_jobs(factory, settings, make_runner):
    runner = make_runner()
    runner.start()
    ids = [add_file(factory, settings, name) for name in ("slow.pdf", "a.pdf", "b.pdf")]
    for file_id in ids:
        runner.enqueue(file_id)
    wait_row(factory, ids[0], statuses=("running",))
    assert runner.queue_depth() == 2


def test_queue_depth_reads_the_db_not_memory(factory, settings, make_runner):
    for name in ("a.pdf", "b.pdf"):
        add_file(factory, settings, name)
    add_file(factory, settings, "c.pdf", status="error")
    assert make_runner().queue_depth() == 2  # chưa start, chưa enqueue gì


def test_rows_queued_by_another_process_are_picked_up(factory, settings, make_runner):
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "doc.pdf")  # không enqueue: chỉ có dòng trong DB
    assert wait_row(factory, file_id).status == "done"


def test_only_one_runner_per_data_dir_processes_jobs(factory, settings, make_runner):
    holder, other = make_runner(), make_runner()
    ran_holder, ran_other = processed_by(holder), processed_by(other)
    holder.start()
    other.start()
    ids = [add_file(factory, settings, name) for name in ("a.pdf", "b.pdf", "c.pdf")]
    for file_id in ids:
        holder.enqueue(file_id)
        other.enqueue(file_id)
    for file_id in ids:
        assert wait_row(factory, file_id).status == "done"
    assert sorted(ran_holder) == sorted(ids) and ran_other == []


def test_runner_without_the_lock_leaves_running_rows_alone(factory, settings, make_runner):
    holder = make_runner()
    holder.start()
    file_id = add_file(factory, settings, "slow.pdf")
    holder.enqueue(file_id)
    started_at = wait_row(factory, file_id, statuses=("running",)).started_at
    late = make_runner()
    ran_late = processed_by(late)
    late.start()  # vd container mới lên khi container cũ còn chạy: không được "cứu" job của nó
    time.sleep(0.5)
    with factory() as db:
        row = db.get(File, file_id)
        assert (row.status, row.started_at) == ("running", started_at)
    assert wait_row(factory, file_id).status == "done"
    assert ran_late == []


def test_waiting_runner_takes_over_when_the_holder_stops(factory, settings, make_runner):
    holder, other = make_runner(), make_runner()
    ran_other = processed_by(other)
    holder.start()
    other.start()
    interrupted = add_file(factory, settings, "slow.pdf")
    holder.enqueue(interrupted)
    wait_row(factory, interrupted, statuses=("running",))
    holder.stop()
    assert wait_row(factory, interrupted).status == "done"  # other giữ khoá, phục hồi, chạy lại
    fresh = add_file(factory, settings, "doc.pdf")
    other.enqueue(fresh)
    assert wait_row(factory, fresh).status == "done"
    assert ran_other == [interrupted, fresh]


def test_finish_only_touches_running_rows(factory, settings, make_runner):
    runner = make_runner()
    file_id = add_file(factory, settings, "doc.pdf")  # vd đã bị runner khác phục hồi về queued
    runner._finish(file_id, status="done", message="Xong", output_name="doc-vi.pdf", done_pages=2, total_pages=2)
    runner._report_progress(file_id, 2, 2)
    with factory() as db:
        row = db.get(File, file_id)
        assert (row.status, row.message, row.output_name, row.done_pages, row.total_pages) == ("queued", "", None, 0, 0)


def test_start_requeues_unfinished_jobs_in_order(factory, settings, make_runner):
    running = add_file(factory, settings, "a.pdf", status="running")
    queued = add_file(factory, settings, "b.pdf", status="queued")
    make_runner().start()  # không enqueue gì: start() tự nhặt lại
    first, second = wait_row(factory, running), wait_row(factory, queued)
    assert first.status == second.status == "done"
    assert first.started_at <= second.started_at


def test_recovering_an_interrupted_job_keeps_its_paid_segment_table(factory, settings, make_runner):
    running = add_file(factory, settings, "a.pdf", status="running")
    directory = file_dir(settings.users_dir, "u1", running)
    (directory / "segments.jsonl").write_text('{"src": "a", "dst": "b"}\n', encoding="utf-8")
    (directory / "segments.meta.json").write_text("{}", encoding="utf-8")
    make_runner().start()
    assert wait_row(factory, running).status == "done"
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "a", "dst": "b"}\n'
    assert (directory / "segments.meta.json").is_file()


def test_stop_leaves_the_running_job_for_the_next_start(factory, settings, make_runner):
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "slow.pdf")
    runner.enqueue(file_id)
    wait_row(factory, file_id, statuses=("running",))
    runner.stop()
    time.sleep(0.3)
    with factory() as db:
        assert db.get(File, file_id).status == "running"
    make_runner().start()
    assert wait_row(factory, file_id).status == "done"


def test_non_int_progress_value_does_not_break_the_job(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "junkprogress.pdf")
    assert row.status == "done", row.message


def test_exception_while_reading_progress_kills_the_child(factory, settings, make_runner, monkeypatch):
    runner = make_runner()

    def boom(*_args):
        raise RuntimeError("boom-progress")

    monkeypatch.setattr(runner, "_report_progress", boom)
    runner.start()
    file_id = add_file(factory, settings, "badprogress.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner.enqueue(file_id)
    row = wait_row(factory, file_id)
    assert row.status == "error", row.message
    time.sleep(4)
    assert not (directory / "late-marker.txt").exists()


def test_run_forever_thread_survives_execute_and_finish_errors(factory, settings, make_runner, monkeypatch):
    runner = make_runner()
    bad_id = add_file(factory, settings, "doc.pdf")
    good_id = add_file(factory, settings, "doc.pdf")

    real_execute = runner._execute

    def fake_execute(file_id):
        if file_id == bad_id:
            raise RuntimeError("boom-execute")
        return real_execute(file_id)

    monkeypatch.setattr(runner, "_execute", fake_execute)

    real_finish = runner._finish
    calls = {"n": 0}

    def fake_finish(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom-finish")
        return real_finish(*args, **kwargs)

    monkeypatch.setattr(runner, "_finish", fake_finish)

    runner.start()
    runner.enqueue(bad_id)
    runner.enqueue(good_id)
    row = wait_row(factory, good_id)
    assert row.status == "done", row.message


def test_failed_recovery_releases_the_lock_so_the_next_try_works(factory, settings, make_runner, monkeypatch):
    holder, waiter = make_runner(), make_runner()
    holder.start()
    calls = []
    real_recover = waiter._recover

    def flaky_recover():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("DB trục trặc đúng lúc tiếp quản")
        real_recover()

    monkeypatch.setattr(waiter, "_recover", flaky_recover)
    waiter.start()
    holder.stop()
    file_id = add_file(factory, settings, "doc.pdf")
    waiter.enqueue(file_id)
    assert wait_row(factory, file_id).status == "done"
    assert len(calls) == 2


def test_handoff_stage_progress_and_messages(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "slow.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    runner.enqueue(file_id)
    row = wait_stage(factory, file_id, "translate")
    assert row.message == "Bước 2/3: Đang dịch bằng Gemini (Google AI Studio)…"
    assert (row.done_pages, row.total_pages) == (0, 5)
    progress = runner.progress(file_id)
    assert progress is not None and progress.stage == "translate" and progress.engine_label == "Gemini (Google AI Studio)"
    row = wait_row(factory, file_id)
    assert row.status == "done" and row.stage == "" and row.untranslated == 1
    assert (row.done_pages, row.total_pages, row.message) == (2, 2, "Xong")


def test_handoff_worker_error_code_message_is_kept(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    row = run_one(factory, settings, make_runner, "fail.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    assert row.status == "error" and row.message == "API key bị từ chối — kiểm tra lại key trong Cài đặt"


def test_unknown_engine_row_fails_cleanly(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "doc.pdf", engine="deepl")
    assert row.status == "error" and "không được hỗ trợ" in row.message


def test_missing_handoff_worker_cmd_fails_without_spawning_anything(factory, settings, make_runner):
    """Runner dựng thiếu `handoff_worker_cmd`: job cần worker handoff phải lỗi NGAY, không bao giờ
    được lùi về worker thường (worker thường không biết dịch qua provider)."""
    add_credential(factory, settings, "gemini")
    runner = make_runner(handoff_worker_cmd=())
    ran = processed_by(runner)
    runner.start()
    file_id = add_file(factory, settings, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    runner.enqueue(file_id)
    row = wait_row(factory, file_id)
    assert row.status == "error" and row.message == NO_HANDOFF_WORKER_MESSAGE
    assert ran == []  # _run_worker không được gọi — không tiến trình con nào được spawn


def test_unknown_stage_from_the_worker_is_not_stored(factory, settings, make_runner):
    """Worker handoff (giả mạo hay hỏng) gửi một `stage` lạ: runner phải đổi về "" thay vì lưu
    nguyên văn — stage hiện ra UI/DB chỉ gồm split/translate/render."""
    add_credential(factory, settings, "gemini")
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "weirdstage.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    runner.enqueue(file_id)
    deadline = time.monotonic() + 5
    stage_seen = None
    while time.monotonic() < deadline:
        with factory() as db:
            row = db.get(File, file_id)
            if row is not None and row.total_pages == 9:  # dòng (stage="mystery", p=1, t=9) của fake worker
                stage_seen = row.stage
                break
        time.sleep(0.02)
    assert stage_seen == ""  # "mystery" không nằm trong whitelist
    assert wait_row(factory, file_id).status == "done"


def test_worker_provided_text_with_the_api_key_is_redacted(factory, settings, make_runner):
    """Worker làm lộ key trong stderr lẫn trong "error" của JSON — runner phải che key trước khi
    lưu message vào DB (dù key luôn đi qua env, không qua các kênh này)."""
    key = "AIza-leaky-secret-0007"
    add_credential(factory, settings, "gemini", key=key)
    row = run_one(factory, settings, make_runner, "leaky.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    assert row.status == "error"
    assert "***" in row.message
    assert key not in row.message


def test_handoff_child_env_excludes_secret_key_and_smtp_password(factory, settings, make_runner, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-smtp-pw")
    monkeypatch.setenv("SETUP_TOKEN", "bi-mat-cai-dat")
    add_credential(factory, settings, "gemini")
    row = run_one(factory, settings, make_runner, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    assert row.status == "done", row.message
    env_seen = json.loads((file_dir(settings.users_dir, "u1", row.id) / "env-seen.json").read_text(encoding="utf-8"))
    assert env_seen["has_secret_key"] is False
    assert env_seen["has_smtp_password"] is False
    assert env_seen["has_setup_token"] is False
    assert env_seen["provider"] == "gemini"  # TRANSLATE_* vẫn phải còn nguyên


SIMPLE = json.dumps({"schema": 1, "mode": "advanced", "profile": None, "style": {"tone": "simple"}, "overrides": ["tone"],
                     "document_context": "Sách giáo khoa."})
ACADEMIC = json.dumps({"schema": 1, "mode": "advanced", "profile": None, "style": {"tone": "academic"}, "overrides": ["tone"],
                       "document_context": None})


def test_the_handoff_worker_receives_the_style_instructions_built_from_the_snapshot(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "ai.pdf", engine="gemini", model="gemini-3.5-flash-lite", config=SIMPLE)
    runner.enqueue(file_id)
    assert wait_row(factory, file_id).status == "done"
    instructions = env_seen(settings, file_id)["instructions"]
    assert instructions.startswith(HEADER) and "- Tone: plain and simple" in instructions and "«Sách giáo khoa.»" in instructions


def test_a_plain_engine_job_gets_no_instructions_and_a_basic_ai_job_gets_an_empty_string(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    runner = make_runner()
    runner.start()
    plain = add_file(factory, settings, "plain.pdf", config=SIMPLE)  # snapshot lạc vào tệp thuần (không thể qua API): bị bỏ qua
    ai = add_file(factory, settings, "ai.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    for file_id in (plain, ai):
        runner.enqueue(file_id)
        assert wait_row(factory, file_id).status == "done"
    assert env_seen(settings, plain)["instructions"] is None  # font_worker không nhận biến này
    assert env_seen(settings, ai)["instructions"] == ""


def test_a_retranslate_builds_the_instructions_from_the_parked_snapshot_not_the_current_one(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "fontline.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    with factory() as db:
        row = db.get(File, file_id)
        row.config, row.retranslate_config = SIMPLE, ACADEMIC
        db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    instructions = env_seen(settings, file_id)["instructions"]
    assert "Tone: formal and precise" in instructions and "plain and simple" not in instructions
    assert json.loads(row.config)["style"]["tone"] == "academic" and row.retranslate_config is None  # đổi chỗ khi xong (Task 3)


def test_a_font_rebuild_builds_the_instructions_from_the_current_snapshot(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif", engine="gemini", model="gemini-3.5-flash-lite")
    with factory() as db:
        db.get(File, file_id).config = SIMPLE
        db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    assert row.status == "done" and json.loads(row.config) == json.loads(SIMPLE)
    assert "- Tone: plain and simple" in env_seen(settings, file_id)["instructions"]


def test_the_digest_the_fake_worker_writes_is_the_real_digest_of_the_instructions_the_runner_built(factory, settings, make_runner):
    """Chốt chống lệch: fake_handoff_worker tự lặp logic băm — phải khớp handoff_worker.instructions_digest thật."""
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "newtable.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    with factory() as db:
        db.get(File, file_id).retranslate_config = SIMPLE
        db.commit()
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    assert wait_row(factory, file_id).status == "done"
    wait_gone(directory / "rebuild")  # bảng mới thay vào thư mục job SAU commit
    instructions = env_seen(settings, file_id)["instructions"]
    meta = json.loads((directory / "segments.meta.json").read_text(encoding="utf-8"))
    assert instructions and meta["instructions"] == instructions_digest(instructions)


# ---- Font bản dịch + dựng lại (spec 2026-10-02 §6) ---------------------------------------------

def add_translated(factory, settings, filename="doc.pdf", *, rebuild_font="serif", status="queued", engine="google_free",
                   model=None, font="auto", font_used="sans", untranslated=2) -> str:
    """Tệp đã dịch xong (bản dịch cũ nằm trên đĩa) vừa được yêu cầu dựng lại — như files.service.rebuild_file."""
    file_id = add_file(factory, settings, filename, status="done", engine=engine, model=model, font=font)
    output_name = f"{Path(filename).stem}-vi.pdf"
    (file_dir(settings.users_dir, "u1", file_id) / output_name).write_bytes(PDF + b"old translation")
    with factory() as db:
        row = db.get(File, file_id)
        row.output_name, row.font_used, row.untranslated, row.message = output_name, font_used, untranslated, ""
        row.rebuild_font, row.status = rebuild_font, status  # cùng một commit: runner không bao giờ thấy nửa vời
        db.commit()
    return file_id


def env_seen(settings, file_id) -> dict:
    return json.loads((file_dir(settings.users_dir, "u1", file_id) / "env-seen.json").read_text(encoding="utf-8"))


def test_both_workers_get_the_font_choice_but_no_server_secrets(factory, settings, make_runner, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-smtp-pw")
    monkeypatch.setenv("SETUP_TOKEN", "bi-mat-cai-dat")
    add_credential(factory, settings, "gemini")
    runner = make_runner()
    runner.start()
    plain = add_file(factory, settings, "plain.pdf")
    ai = add_file(factory, settings, "ai.pdf", engine="gemini", model="gemini-3.5-flash-lite", font="serif")
    for file_id in (plain, ai):
        runner.enqueue(file_id)
    for file_id, font in ((plain, "auto"), (ai, "serif")):
        assert wait_row(factory, file_id).status == "done"
        seen = env_seen(settings, file_id)
        assert seen["font"] == font
        assert seen["has_secret_key"] is False and seen["has_smtp_password"] is False and seen["has_setup_token"] is False


def test_the_font_line_becomes_font_used_when_the_job_is_done(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "fontline.pdf", font="serif")
    assert row.status == "done" and (row.font, row.font_used) == ("serif", "serif")


def test_without_a_font_line_font_used_stays_empty(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "doc.pdf")
    assert row.status == "done" and (row.font, row.font_used) == ("auto", None)


def test_a_rebuild_replaces_the_translation_from_a_staging_folder(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.message, row.output_name) == ("done", "Xong", "fontline-vi.pdf")
    assert (row.font, row.font_used, row.rebuild_font, row.rebuild_error, row.untranslated) == ("serif", "serif", None, "", 0)
    assert (directory / "fontline-vi.pdf").read_bytes().endswith(b"% rebuilt font=serif\n")
    wait_gone(directory / "rebuild")  # rmtree rebuild/ chạy SAU commit
    seen = env_seen(settings, file_id)
    assert seen["font"] == "serif" and seen["argv"][1] == str(directory / "rebuild")


def test_a_failed_rebuild_keeps_the_previous_translation(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "rebuildfail.pdf", font="auto", font_used="sans", untranslated=2)
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.message, row.output_name) == ("done", "Xong", "rebuildfail-vi.pdf")
    assert (row.font, row.font_used, row.rebuild_font, row.untranslated) == ("auto", "sans", None, 2)
    assert row.rebuild_error == "Dựng lại thất bại (worker giả)."
    assert (directory / "rebuildfail-vi.pdf").read_bytes() == PDF + b"old translation"
    assert "rebuild boom" in (directory / "rebuild-stderr.log").read_text(encoding="utf-8")
    assert not (directory / "rebuild").exists()


def test_a_stalled_rebuild_is_also_rolled_back(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "rebuildhang.pdf")
    make_runner(stall_seconds=1).start()
    row = wait_row(factory, file_id)
    assert (row.status, row.rebuild_font, row.font) == ("done", None, "auto")
    assert "không nhích thêm trang nào" in row.rebuild_error
    assert (file_dir(settings.users_dir, "u1", file_id) / "rebuildhang-vi.pdf").read_bytes() == PDF + b"old translation"


def test_an_internal_error_during_a_rebuild_is_rolled_back(factory, settings, make_runner, monkeypatch):
    file_id = add_translated(factory, settings, "doc.pdf")
    runner = make_runner()

    def boom(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_run_worker", boom)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.message, row.rebuild_font, row.rebuild_error) == ("done", "Xong", None, "Lỗi nội bộ (RuntimeError).")
    assert (file_dir(settings.users_dir, "u1", file_id) / "doc-vi.pdf").read_bytes() == PDF + b"old translation"


def test_an_internal_error_shows_only_the_exception_class_and_logs_the_details(
        factory, settings, make_runner, monkeypatch, caplog):
    file_id = add_file(factory, settings, "doc.pdf")
    runner = make_runner()
    secret_path = f"/data/users/u1/{file_id}/rebuild/doc-vi.pdf"

    def boom(*_args):
        raise OSError(28, "No space left on device", secret_path)

    monkeypatch.setattr(runner, "_run_worker", boom)
    caplog.set_level("ERROR", logger="engine")
    runner.start()
    row = wait_row(factory, file_id)
    # Người dùng chỉ thấy tên lớp lỗi; đường dẫn máy chủ / errno nằm trong log, không lên giao diện.
    assert (row.status, row.message) == ("error", "Lỗi nội bộ (OSError).")
    assert secret_path in caplog.text and "No space left on device" in caplog.text


def test_recovery_keeps_the_rebuild_request(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf", status="running")  # container chết giữa lúc dựng lại
    (file_dir(settings.users_dir, "u1", file_id) / "rebuild").mkdir()  # thư mục dở dang của lần chạy trước
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.font, row.font_used, row.rebuild_font) == ("done", "serif", "serif", None)


def test_a_gemini_rebuild_reuses_the_paid_segment_table(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_translated(factory, settings, "fontline.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "segments.jsonl").write_text('{"src": "a", "dst": "b"}\n', encoding="utf-8")
    (directory / "segments.meta.json").write_text("{}", encoding="utf-8")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.font, row.rebuild_font) == ("done", "serif", None)
    seen = env_seen(settings, file_id)
    assert seen["table_seen"] is True and seen["provider"] == "gemini" and seen["font"] == "serif"
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "a", "dst": "b"}\n'


def test_a_rebuild_without_a_usable_key_rolls_back_with_the_reason(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.rebuild_font) == ("done", None)
    assert row.rebuild_error == MISSING_KEY_MESSAGE.format(provider="Gemini (Google AI Studio)")
    assert not (file_dir(settings.users_dir, "u1", file_id) / "env-seen.json").exists()


# ---- Model Gemini bị Google gỡ (spec 2026-10-02 §3) ---------------------------------------------

KEY_MODELS = json.dumps([{"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite"},
                         {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"}])
GONE = "Model này không còn dùng được. Tải tệp lên lại và chọn model khác."


def stored_models(factory) -> list[str]:
    with factory() as db:
        return [m["id"] for m in json.loads(db.get(ApiCredential, "c-gemini").models)]


def defaults(factory) -> tuple:
    with factory() as db:
        user = db.get(User, "u1")
        return user.default_engine, user.default_model


def test_model_unavailable_drops_the_model_and_says_what_the_default_is_now(factory, settings, make_runner):
    add_credential(factory, settings, "gemini", models=KEY_MODELS)
    with factory() as db:
        user = db.get(User, "u1")
        user.default_engine, user.default_model = "gemini", "gemini-3.8-flash"
        db.commit()
    row = run_one(factory, settings, make_runner, "gone.pdf", engine="gemini", model="gemini-3.8-flash")
    assert row.status == "error" and row.model == "gemini-3.8-flash"  # files.model giữ nguyên (lịch sử)
    assert row.message == GONE + " Đã gỡ model khỏi danh sách của key; model mặc định hiện là Gemini 3.5 Flash-Lite."
    assert stored_models(factory) == ["gemini-3.5-flash-lite"]
    assert defaults(factory) == ("gemini", "gemini-3.5-flash-lite")


def test_model_unavailable_for_a_model_that_is_not_the_default_keeps_the_message(factory, settings, make_runner):
    add_credential(factory, settings, "gemini", models=KEY_MODELS)  # mặc định của u1 vẫn là google_free
    row = run_one(factory, settings, make_runner, "gone.pdf", engine="gemini", model="gemini-3.8-flash")
    assert row.status == "error" and row.message == GONE
    assert stored_models(factory) == ["gemini-3.5-flash-lite"]
    assert defaults(factory) == ("google_free", None)


def test_other_worker_errors_leave_the_model_list_alone(factory, settings, make_runner):
    add_credential(factory, settings, "gemini", models=KEY_MODELS)
    row = run_one(factory, settings, make_runner, "fail.pdf", engine="gemini", model="gemini-3.8-flash")
    assert row.status == "error" and row.message == "API key bị từ chối — kiểm tra lại key trong Cài đặt"
    assert stored_models(factory) == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]


# ---- Gia cố runner từ review Task 9 ---------------------------------------------------------------

def test_a_rebuild_keeps_the_old_output_when_the_database_write_fails(factory, settings, make_runner, monkeypatch):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "old-name.pdf").write_bytes(PDF + b"old translation")
    with factory() as db:
        db.get(File, file_id).output_name = "old-name.pdf"  # tên bản mới (fontline-vi.pdf) khác bản cũ
        db.commit()
    runner = make_runner()
    real, calls = runner._update_running, []

    def flaky(target, values):
        calls.append(values)
        if len(calls) == 1:
            raise RuntimeError("disk full")  # lần ghi DB của _finish_rebuild
        real(target, values)

    monkeypatch.setattr(runner, "_update_running", flaky)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.rebuild_font) == ("done", "old-name.pdf", None)
    assert row.rebuild_error == "Lỗi nội bộ (RuntimeError)."
    assert (directory / "old-name.pdf").read_bytes() == PDF + b"old translation"  # bản cũ chưa bị xoá
    assert not (directory / "fontline-vi.pdf").exists() and not (directory / "rebuild").exists()


def test_a_rebuild_removes_the_old_output_after_the_database_update(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "old-name.pdf").write_bytes(PDF + b"old translation")
    with factory() as db:
        db.get(File, file_id).output_name = "old-name.pdf"
        db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name) == ("done", "fontline-vi.pdf")
    assert (directory / "fontline-vi.pdf").read_bytes().endswith(b"% rebuilt font=serif\n")
    assert not (directory / "old-name.pdf").exists()


def test_a_malformed_font_line_is_ignored_like_a_malformed_progress_line(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "fontjunk.pdf")
    assert (row.status, row.message, row.font_used) == ("done", "Xong", None)


@pytest.mark.parametrize("marker", ["tablename", "stderrname"])
def test_a_worker_cannot_report_a_reserved_file_as_its_output(factory, settings, make_runner, marker):
    row = run_one(factory, settings, make_runner, f"{marker}.pdf")
    assert row.status == "error" and row.output_name is None
    assert row.message == "Nhân dịch báo xong nhưng không tìm thấy tệp kết quả."


def test_a_rebuild_cannot_overwrite_the_upload_through_the_staging_folder(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "clobber.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.rebuild_font, row.font) == ("done", "clobber-vi.pdf", None, "auto")
    assert row.rebuild_error == "Nhân dịch báo xong nhưng không tìm thấy tệp kết quả."
    assert (directory / "clobber.pdf").read_bytes() == PDF  # bản tải lên của người dùng còn nguyên
    assert (directory / "clobber-vi.pdf").read_bytes() == PDF + b"old translation"


def test_a_failed_rebuild_keeps_the_segments_the_worker_added(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "rebuildfail-tablegrow.pdf", engine="google_free")
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "segments.jsonl").write_text("old\n", encoding="utf-8")
    (directory / "segments.meta.json").write_text("meta\n", encoding="utf-8")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.rebuild_font) == ("done", None) and row.rebuild_error
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\ngrown\n"
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == "meta\ngrown\n"
    assert not (directory / "rebuild").exists()


def flaky_first_update(runner, monkeypatch):
    real, calls = runner._update_running, []

    def flaky(target, values):
        calls.append(values)
        if len(calls) == 1:
            raise RuntimeError("disk full")  # lần ghi DB của _finish_rebuild
        return real(target, values)

    monkeypatch.setattr(runner, "_update_running", flaky)


def test_a_rebuild_with_the_same_output_name_survives_a_database_failure(factory, settings, make_runner, monkeypatch):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")  # tên mới == tên cũ (như thật)
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    flaky_first_update(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.font, row.font_used, row.untranslated) == ("done", "fontline-vi.pdf", "auto", "sans", 2)
    assert row.rebuild_font is None and row.rebuild_error == "Lỗi nội bộ (RuntimeError)."
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"  # DB và đĩa cùng nói "bản cũ"
    assert not (directory / "rebuild").exists()


def seed_tables(directory):
    (directory / "segments.jsonl").write_text("old\n", encoding="utf-8")
    (directory / "segments.meta.json").write_text("meta\n", encoding="utf-8")


def test_a_failed_rebuild_keeps_the_job_table_when_the_staging_copy_is_not_an_extension(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "rebuildfail-tablejunk.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    seed_tables(directory)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert row.status == "done" and row.rebuild_error
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == "meta\n"


def test_staging_keeps_segments_added_by_an_interrupted_rebuild(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    seed_tables(directory)
    (directory / "rebuild").mkdir()  # lượt dựng lại bị ngắt: bảng trong rebuild/ đã được bổ sung
    (directory / "rebuild" / "segments.jsonl").write_text("old\npaid\n", encoding="utf-8")
    (directory / "rebuild" / "segments.meta.json").write_text("meta2\n", encoding="utf-8")
    runner = make_runner()
    assert runner._staging(directory) == directory / "rebuild"
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\npaid\n"
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == "meta2\n"


def test_model_unavailable_on_google_cloud_does_not_touch_the_gemini_models(factory, settings, make_runner):
    add_credential(factory, settings, "gemini", models=KEY_MODELS)
    add_credential(factory, settings, "google_cloud")
    with factory() as db:
        user = db.get(User, "u1")
        user.default_engine, user.default_model = "gemini", "gemini-3.8-flash"
        db.commit()
    row = run_one(factory, settings, make_runner, "gone.pdf", engine="google_cloud", model="gemini-3.8-flash")
    assert row.status == "error" and row.message == GONE
    assert stored_models(factory) == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert defaults(factory) == ("gemini", "gemini-3.8-flash")


# ---- Vòng 2: thay bản dịch không được làm mất bản cũ --------------------------------------------

def fail_replace_once(monkeypatch, *, dst_name, src_name=None):
    """os.replace lỗi đúng một lần khi đích có tên dst_name (và nguồn có tên src_name nếu cho)."""
    from app.engine import jobs
    real, state = jobs.os.replace, {"left": 1}

    def replace(src, dst, *args, **kwargs):
        if state["left"] and Path(dst).name == dst_name and (src_name is None or Path(src).name == src_name):
            state["left"] -= 1
            raise OSError(28, "No space left on device")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(jobs.os, "replace", replace)


def test_a_failed_backup_move_leaves_the_old_output_alone(factory, settings, make_runner, monkeypatch):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    fail_replace_once(monkeypatch, dst_name=".previous")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.font, row.font_used, row.rebuild_font) == ("done", "fontline-vi.pdf", "auto", "sans", None)
    assert row.rebuild_error == "Lỗi nội bộ (OSError)."  # errno/đường dẫn chỉ nằm trong log
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"


def test_abort_rescues_the_backup_when_the_put_back_itself_fails(factory, settings, make_runner, monkeypatch):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    flaky_first_update(runner, monkeypatch)
    fail_replace_once(monkeypatch, dst_name="fontline-vi.pdf", src_name=".previous")  # trả bản cũ lần đầu lỗi
    runner.start()
    row = wait_row(factory, file_id)
    assert row.rebuild_error == "Lỗi nội bộ (RuntimeError)." and row.output_name == "fontline-vi.pdf"
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "rebuild").exists()


def test_staging_moves_a_stranded_backup_back(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "rebuild").mkdir()  # chết giữa lúc thay: bản cũ chỉ còn trong .previous
    (directory / "fontline-vi.pdf").replace(directory / "rebuild" / ".previous")
    make_runner()._staging(directory, "fontline-vi.pdf")
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "rebuild" / ".previous").exists()


def test_a_worker_cannot_report_the_backup_name_as_its_output(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "previousname.pdf", rebuild_font="serif")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert row.rebuild_error == "Nhân dịch báo xong nhưng không tìm thấy tệp kết quả."
    assert (directory / "previousname-vi.pdf").read_bytes() == PDF + b"old translation"


def test_finish_rebuild_puts_everything_back_when_the_row_is_no_longer_running(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif", status="queued")  # đã bị phục hồi
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "rebuild").mkdir()
    (directory / "rebuild" / "fontline-vi.pdf").write_bytes(b"new render")
    make_runner()._finish_rebuild(file_id, "u1", "serif", "fontline-vi.pdf", retranslate=None, message="Xong",
                                  output_name="fontline-vi.pdf", untranslated=0, font_used="serif")
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    with factory() as db:
        row = db.get(File, file_id)
        assert (row.status, row.font, row.rebuild_font) == ("queued", "auto", "serif")


def line(src, dst):
    return json.dumps({"src": src, "dst": dst}) + "\n"


def test_restore_tables_accepts_a_staging_table_holding_every_valid_job_line(tmp_path):
    from app.engine.jobs import _restore_tables
    job, staging = tmp_path, tmp_path / "rebuild"
    staging.mkdir()
    (job / "segments.jsonl").write_text(line("a", "A") + '{"src": "b", "dst"', encoding="utf-8")  # dòng cuối bị cụt
    (job / "segments.meta.json").write_text("old", encoding="utf-8")
    (staging / "segments.jsonl").write_text(line("a", "A") + line("c", "C"), encoding="utf-8")  # _resume viết lại
    (staging / "segments.meta.json").write_text("new", encoding="utf-8")
    _restore_tables(job, staging)
    assert (job / "segments.jsonl").read_text(encoding="utf-8") == line("a", "A") + line("c", "C")
    assert (job / "segments.meta.json").read_text(encoding="utf-8") == "new"


@pytest.mark.parametrize("junk", ["JUNK", line("z", "Z") + "JUNK\n", line("z", "Z")])
def test_restore_tables_rejects_junk_or_lossy_staging_tables(tmp_path, junk):
    from app.engine.jobs import _restore_tables
    job, staging = tmp_path, tmp_path / "rebuild"
    staging.mkdir()
    (job / "segments.jsonl").write_text(line("a", "A"), encoding="utf-8")
    (job / "segments.meta.json").write_text("old", encoding="utf-8")
    (staging / "segments.jsonl").write_text(junk, encoding="utf-8")
    (staging / "segments.meta.json").write_text("new", encoding="utf-8")
    _restore_tables(job, staging)
    assert (job / "segments.jsonl").read_text(encoding="utf-8") == line("a", "A")
    assert (job / "segments.meta.json").read_text(encoding="utf-8") == "old"


# ---- Dịch lại từ đầu (spec 2026-10-05 §6) ----------------------------------------------------------


def add_retranslate(factory, settings, filename="doc.pdf", *, language="en", engine="google_free", model=None, font="serif",
                    status="queued", old_engine="google_free", old_model=None) -> str:
    """Tệp đã xong (bản cũ + bảng đoạn cũ "old\\n" trên đĩa) vừa được yêu cầu dịch lại từ đầu — như files.service.retranslate_file."""
    file_id = add_translated(factory, settings, filename, rebuild_font=font, status=status, engine=old_engine, model=old_model)
    seed_tables(file_dir(settings.users_dir, "u1", file_id))
    with factory() as db:
        row = db.get(File, file_id)
        row.retranslate_language, row.retranslate_engine, row.retranslate_model = language, engine, model
        db.commit()
    return file_id


def test_a_retranslate_runs_in_staging_with_the_new_choice_and_without_the_old_table(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en", engine="gemini", model="gemini-3.8-flash", font="sans")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.message, row.output_name) == ("done", "Xong", "fontline-en.pdf")
    assert (row.language, row.engine, row.model, row.font, row.font_used) == ("en", "gemini", "gemini-3.8-flash", "sans", "sans")
    assert (row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.rebuild_font, row.rebuild_error) == (
        None, None, None, None, "")
    assert row.untranslated == 1  # theo kết quả mới (worker handoff giả báo 1)
    seen = env_seen(settings, file_id)
    assert (seen["provider"], seen["model"], seen["font"]) == ("gemini", "gemini-3.8-flash", "sans")
    assert seen["argv"][1:] == [str(directory / "rebuild"), "en"]
    assert seen["table_seen"] is False  # KHÔNG chép bảng cũ vào staging: dịch từ đầu đúng quyết định của người dùng
    assert (directory / "fontline-en.pdf").read_bytes().endswith(b"% rebuilt font=sans\n")
    wait_gone(directory / "rebuild")  # thay bảng + rmtree rebuild/ chạy SAU commit (spec 2026-10-14 §5 bước 6)
    assert not (directory / "fontline-vi.pdf").exists()
    # Bảng cũ thuộc lựa chọn cũ: bị thay hẳn — worker không ghi bảng mới thì không còn bảng nào.
    assert not (directory / "segments.jsonl").exists() and not (directory / "segments.meta.json").exists()


def test_a_retranslate_replaces_the_old_table_with_the_new_one_without_merging(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "newtable.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.language, row.engine) == ("done", "en", "gemini")
    wait_gone(directory / "rebuild")  # thay bảng chạy SAU commit, trước bước cuối rmtree rebuild/
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "x", "dst": "y"}\n'  # không nối "old\n"
    assert json.loads((directory / "segments.meta.json").read_text(encoding="utf-8")) == {
        "provider": "gemini", "model": "gemini-3.5-flash-lite", "target_language": "en", "instructions": ""}


def test_a_failed_retranslate_keeps_the_old_translation_and_table(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "newtable-rebuildfail.pdf", engine="gemini", model="gemini-3.5-flash-lite", font="sans")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.message, row.output_name) == ("done", "Xong", "newtable-rebuildfail-vi.pdf")
    assert (row.language, row.engine, row.model, row.font, row.font_used, row.untranslated) == ("vi", "google_free", None, "auto", "sans", 2)
    assert (row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.rebuild_font) == (None, None, None, None)
    assert row.rebuild_error == "Dựng lại thất bại (worker giả)."
    assert (directory / "newtable-rebuildfail-vi.pdf").read_bytes() == PDF + b"old translation"
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"  # bảng cũ nguyên — không bị bảng lựa chọn mới đè/nối
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == "meta\n"
    assert not (directory / "rebuild").exists()


def test_a_stalled_retranslate_is_rolled_back(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "rebuildhang.pdf", language="en")
    make_runner(stall_seconds=1).start()
    row = wait_row(factory, file_id)
    assert (row.status, row.language, row.retranslate_language, row.rebuild_font) == ("done", "vi", None, None)
    assert "không nhích thêm trang nào" in row.rebuild_error
    assert (file_dir(settings.users_dir, "u1", file_id) / "rebuildhang-vi.pdf").read_bytes() == PDF + b"old translation"


def test_recovery_keeps_the_retranslate_request_and_its_staged_table(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "fontline.pdf", engine="gemini", model="gemini-3.5-flash-lite", status="running")
    directory = file_dir(settings.users_dir, "u1", file_id)
    staging = directory / "rebuild"  # container chết giữa lượt dịch lại: bảng dở (đã trả tiền) của lựa chọn MỚI nằm đây
    staging.mkdir()
    (staging / "segments.jsonl").write_text('{"src": "paid", "dst": "tra-tien"}\n', encoding="utf-8")
    (staging / "segments.meta.json").write_text("meta-new\n", encoding="utf-8")
    (staging / "rac.txt").write_text("rac", encoding="utf-8")  # mọi thứ khác trong rebuild/ bị dọn
    (staging / "fontline-en.pdf").write_bytes(b"ban do dang")  # bản ra dở của lượt bị ngắt
    (staging / "cu").mkdir()
    (staging / "cu" / "trang-1.png").write_bytes(b"png")
    make_runner().start()  # _recover: running → queued, giữ retranslate_* và rebuild_font
    row = wait_row(factory, file_id)
    assert (row.status, row.language, row.engine, row.model, row.font) == ("done", "en", "gemini", "gemini-3.5-flash-lite", "serif")
    seen = env_seen(settings, file_id)
    assert seen["table_seen"] is True  # bảng dở của CHÍNH lượt dịch lại được giữ cho worker handoff tiếp tục
    # Worker chỉ thấy bảng đã trả tiền (+ log stderr runner mở trước khi chạy): tệp/thư mục rác của lượt dở đã bị dọn.
    assert seen["out_dir_listing"] == ["segments.jsonl", "segments.meta.json", "worker-stderr.log"]
    wait_gone(directory / "rebuild")  # thay bảng + rmtree rebuild/ chạy SAU commit
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "paid", "dst": "tra-tien"}\n'  # và thay hẳn bảng cũ


def test_a_retranslate_without_a_rebuild_font_still_runs_staged_with_the_files_font(factory, settings, make_runner):
    """Phòng thủ: retranslate_* khác NULL mà rebuild_font NULL (service luôn ghi cả hai trong một UPDATE, nhưng runner không
    dựa vào đó) — vẫn chạy trong rebuild/, font lùi về font của tệp, xong thì nhãn khớp bản mới."""
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    with factory() as db:
        db.get(File, file_id).rebuild_font = None
        db.commit()
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.engine, row.model, row.font, row.font_used) == (
        "done", "fontline-en.pdf", "en", "google_free", None, "auto", "sans")
    assert (row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.rebuild_font, row.rebuild_error) == (
        None, None, None, None, "")
    seen = env_seen(settings, file_id)
    assert (seen["argv"][1], seen["font"]) == (str(directory / "rebuild"), "auto")
    assert (directory / "fontline-en.pdf").read_bytes().endswith(b"% rebuilt font=auto\n")
    wait_gone(directory / "rebuild")  # thay bảng + rmtree rebuild/ chạy SAU commit
    assert not (directory / "fontline-vi.pdf").exists()
    assert not (directory / "segments.jsonl").exists()  # bảng cũ thuộc lựa chọn cũ: bị thay như mọi lượt dịch lại


def test_a_retranslate_without_a_usable_key_rolls_back_with_the_reason(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite")  # không có credential
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.language, row.engine, row.retranslate_language, row.rebuild_font) == ("done", "vi", "google_free", None, None)
    assert row.rebuild_error == MISSING_KEY_MESSAGE.format(provider="Gemini (Google AI Studio)")
    assert (file_dir(settings.users_dir, "u1", file_id) / "doc-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (file_dir(settings.users_dir, "u1", file_id) / "env-seen.json").exists()


def test_model_unavailable_during_a_retranslate_drops_the_retranslate_model(factory, settings, make_runner):
    add_credential(factory, settings, "gemini", models=KEY_MODELS)
    file_id = add_retranslate(factory, settings, "gone.pdf", engine="gemini", model="gemini-3.8-flash",
                              old_engine="gemini", old_model="gemini-3.5-flash-lite")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.engine, row.model, row.retranslate_model) == ("done", "gemini", "gemini-3.5-flash-lite", None)  # bản cũ giữ model cũ
    assert row.rebuild_error.startswith(GONE)
    assert stored_models(factory) == ["gemini-3.5-flash-lite"]  # gỡ ĐÚNG retranslate_model, không phải model của bản cũ


def test_a_retranslate_keeps_the_old_translation_table_and_labels_when_the_database_write_fails(
        factory, settings, make_runner, monkeypatch):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "newtable.pdf", engine="gemini", model="gemini-3.5-flash-lite")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    fail_commit_swap(runner, monkeypatch)  # giao dịch ghi của lượt dịch lại hỏng SAU khi bản mới (tên khác) đã được chép vào
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.engine, row.model, row.font) == (
        "done", "newtable-vi.pdf", "vi", "google_free", None, "auto")
    assert (row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.rebuild_font) == (None, None, None, None)
    assert row.rebuild_error == "Lỗi nội bộ (RuntimeError)."
    assert (directory / "newtable-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "newtable-en.pdf").exists() and not (directory / "rebuild").exists()
    # Bảng chỉ được thay SAU khi DB đã trỏ sang lựa chọn mới; lỗi nội bộ cũng không trả bảng mới về job.
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == "meta\n"


# ---- Phiên bản (spec 2026-10-14 §5) -----------------------------------------------------------------------------


def versions_of(factory, file_id) -> list[FileVersion]:
    with factory() as db:
        return list(db.scalars(select(FileVersion).where(FileVersion.file_id == file_id).order_by(FileVersion.version_no)).all())


def set_max_versions(factory, value) -> None:
    with factory() as db:
        instance_row(db).max_versions = value
        db.commit()


def requeue_retranslate(factory, file_id, *, language="en", engine="google_free", model=None, font="serif") -> None:
    """Tệp đã xong được yêu cầu dịch lại lần nữa — như files.service._queue_retranslate nhánh done."""
    with factory() as db:
        row = db.get(File, file_id)
        row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.rebuild_font = language, engine, model, font
        row.status, row.done_pages, row.total_pages, row.message, row.stage = "queued", 0, 0, "", ""
        db.commit()


def fail_commit_swap(runner, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")  # giao dịch ghi của lượt dịch lại hỏng SAU khi đã cất bản cũ / chép bản mới

    monkeypatch.setattr(runner, "_commit_swap", boom)


def version_dirs(directory) -> list[str]:
    store = directory / "versions"
    return sorted(child.name for child in store.iterdir()) if store.exists() else []


def seed_version(factory, directory, file_id, *, version_no=1, output_name="archived-en.pdf") -> str:
    """Kho đã có một bản cũ (dòng + tệp) từ lượt dịch lại trước; bản hiện tại thành "Bản version_no + 1"."""
    version_id = uuid.uuid4().hex[:12]
    (directory / "versions" / version_id).mkdir(parents=True)
    (directory / "versions" / version_id / output_name).write_bytes(b"archived v1")
    with factory() as db:
        db.add(FileVersion(id=version_id, file_id=file_id, version_no=version_no, language="en", engine="google_free", font="auto",
                           output_name=output_name, untranslated=0, archived_at=utcnow()))
        db.get(File, file_id).version_no = version_no + 1
        db.commit()
    return version_id


def test_a_retranslate_archives_the_previous_translation_as_a_version(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en", engine="gemini", model="gemini-3.8-flash", font="sans",
                              old_engine="gemini", old_model="gemini-3.5-flash-lite")
    with factory() as db:
        row = db.get(File, file_id)
        row.config, row.retranslate_config = SIMPLE, ACADEMIC
        db.commit()
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no, row.config, row.retranslate_config) == ("done", "fontline-en.pdf", 2, ACADEMIC, None)
    [version] = versions_of(factory, file_id)
    assert (version.version_no, version.language, version.engine, version.model, version.font, version.font_used, version.untranslated) == (
        1, "vi", "gemini", "gemini-3.5-flash-lite", "auto", "sans", 2)
    assert version.config == SIMPLE and version.output_name == "fontline-vi.pdf" and version.archived_at is not None
    assert (directory / "versions" / version.id / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert (directory / "fontline-en.pdf").read_bytes().endswith(b"% rebuilt font=sans\n")
    wait_gone(directory / "rebuild")
    assert not (directory / "fontline-vi.pdf").exists()
    assert version_dirs(directory) == [version.id]


def test_an_archived_version_keeps_the_snapshot_of_the_translation_it_was(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")  # lượt mới chạy cơ bản (retranslate_config NULL)
    with factory() as db:
        db.get(File, file_id).config = SIMPLE
        db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.config) == ("done", None)
    assert versions_of(factory, file_id)[0].config == SIMPLE


def test_version_numbers_keep_counting_and_the_oldest_versions_are_pruned_to_the_limit(factory, settings, make_runner):
    set_max_versions(factory, 3)  # hiện tại + 2 bản cũ
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    runner.start()
    assert wait_row(factory, file_id).version_no == 2
    for number in (3, 4, 5):
        requeue_retranslate(factory, file_id, language="vi" if number % 2 else "en")
        runner.enqueue(file_id)
        assert wait_row(factory, file_id).version_no == number
    versions = versions_of(factory, file_id)
    assert [version.version_no for version in versions] == [3, 4]  # bản 1, 2 đã bị tỉa; nhãn "Bản 3"/"Bản 4" không đổi
    wait_gone(directory / "rebuild")  # rmtree thư mục đã tỉa chạy sau commit
    assert version_dirs(directory) == sorted(version.id for version in versions)
    for version in versions:
        assert (directory / "versions" / version.id / version.output_name).is_file()


def test_lowering_max_versions_prunes_lazily_on_the_next_archive(factory, settings, make_runner):
    set_max_versions(factory, 5)
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    runner.start()
    wait_row(factory, file_id)
    for number in (3, 4, 5):
        requeue_retranslate(factory, file_id, language="vi" if number % 2 else "en")
        runner.enqueue(file_id)
        wait_row(factory, file_id)
    assert [version.version_no for version in versions_of(factory, file_id)] == [1, 2, 3, 4]
    set_max_versions(factory, 2)
    assert [version.version_no for version in versions_of(factory, file_id)] == [1, 2, 3, 4]  # hạ hạn không quét: chưa tỉa gì
    wait_gone(directory / "rebuild")
    assert len(version_dirs(directory)) == 4
    requeue_retranslate(factory, file_id, language="en")
    runner.enqueue(file_id)
    assert wait_row(factory, file_id).version_no == 6
    [kept] = versions_of(factory, file_id)
    wait_gone(directory / "rebuild")
    assert kept.version_no == 5 and version_dirs(directory) == [kept.id]


def test_with_max_versions_one_nothing_is_archived_old_versions_are_pruned_and_the_number_still_grows(factory, settings, make_runner):
    set_max_versions(factory, 3)
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    runner.start()
    wait_row(factory, file_id)
    assert len(versions_of(factory, file_id)) == 1
    set_max_versions(factory, 1)
    requeue_retranslate(factory, file_id, language="vi")
    runner.enqueue(file_id)
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no, row.output_name) == ("done", 3, "fontline-vi.pdf")
    wait_gone(directory / "rebuild")
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []
    assert not (directory / "fontline-en.pdf").exists()


def test_a_font_rebuild_neither_archives_nor_bumps_the_version(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.font, row.version_no) == ("done", "serif", 1) and versions_of(factory, file_id) == []


def test_retranslating_a_failed_file_in_place_keeps_version_one(factory, settings, make_runner):
    runner = make_runner()
    runner.start()
    file_id = add_file(factory, settings, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite")  # chưa có key → lỗi
    runner.enqueue(file_id)
    assert wait_row(factory, file_id).status == "error"
    add_credential(factory, settings, "gemini")  # "Thêm key trong Cài đặt rồi bấm Dịch lại"
    with factory() as db:  # như files.service._queue_retranslate nhánh error: tại chỗ, ghi thẳng lựa chọn + config mới
        row = db.get(File, file_id)
        row.status, row.language, row.config, row.message, row.rebuild_error = "queued", "en", SIMPLE, "", ""
        row.output_name, row.started_at, row.finished_at = None, None, None
        db.commit()
    runner.enqueue(file_id)
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.config, row.version_no) == ("done", "doc-en.pdf", "en", SIMPLE, 1)
    assert row.retranslate_language is None and row.rebuild_font is None  # không qua nhánh staged
    directory = file_dir(settings.users_dir, "u1", file_id)
    assert (directory / "doc-en.pdf").is_file()
    assert versions_of(factory, file_id) == [] and not (directory / "versions").exists()


def test_a_failed_retranslate_leaves_the_version_store_alone(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "newtable-rebuildfail.pdf", engine="gemini", model="gemini-3.5-flash-lite", font="sans")
    with factory() as db:
        db.get(File, file_id).retranslate_config = ACADEMIC
        db.commit()
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no, row.config, row.retranslate_config) == ("done", 1, None, None)
    assert row.rebuild_error == "Dựng lại thất bại (worker giả)."
    assert versions_of(factory, file_id) == [] and not (directory / "versions").exists()
    assert (directory / "newtable-rebuildfail-vi.pdf").read_bytes() == PDF + b"old translation"


@pytest.mark.parametrize("limits", [{"stall_seconds": 1}, {"stall_seconds": 30, "timeout_seconds": 1}], ids=["stall", "timeout"])
def test_a_stalled_or_expired_retranslate_leaves_the_existing_versions_alone(factory, settings, make_runner, limits):
    file_id = add_retranslate(factory, settings, "rebuildhang.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    kept = seed_version(factory, directory, file_id)
    with factory() as db:
        row = db.get(File, file_id)
        row.config, row.retranslate_config = SIMPLE, ACADEMIC
        db.commit()
    make_runner(**limits).start()
    row = wait_row(factory, file_id)
    assert (row.status, row.language, row.version_no, row.config, row.retranslate_config) == ("done", "vi", 2, SIMPLE, None)
    assert row.rebuild_error.startswith("Dừng vì" if "timeout_seconds" not in limits else "Quá")
    assert [version.id for version in versions_of(factory, file_id)] == [kept] and version_dirs(directory) == [kept]
    assert (directory / "versions" / kept / "archived-en.pdf").read_bytes() == b"archived v1"
    assert (directory / "rebuildhang-vi.pdf").read_bytes() == PDF + b"old translation"


def test_a_retranslate_without_a_usable_key_leaves_the_existing_versions_alone(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite")  # không có credential
    directory = file_dir(settings.users_dir, "u1", file_id)
    kept = seed_version(factory, directory, file_id)
    with factory() as db:
        row = db.get(File, file_id)
        row.config, row.retranslate_config = SIMPLE, ACADEMIC
        db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.engine, row.version_no, row.config, row.retranslate_config) == ("done", "google_free", 2, SIMPLE, None)
    assert row.rebuild_error == MISSING_KEY_MESSAGE.format(provider="Gemini (Google AI Studio)")
    assert [version.id for version in versions_of(factory, file_id)] == [kept] and version_dirs(directory) == [kept]
    assert (directory / "versions" / kept / "archived-en.pdf").read_bytes() == b"archived v1"
    assert (directory / "doc-vi.pdf").read_bytes() == PDF + b"old translation"


def test_a_database_failure_after_archiving_puts_the_old_translation_back_and_leaves_no_version(factory, settings, make_runner, monkeypatch):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    fail_commit_swap(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.version_no, row.retranslate_language) == ("done", "fontline-vi.pdf", "vi", 1, None)
    assert row.rebuild_error == "Lỗi nội bộ (RuntimeError)."
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "fontline-en.pdf").exists() and not (directory / "rebuild").exists()
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []


def test_a_failed_archive_move_puts_the_old_translation_back_without_leaving_an_empty_version_folder(
        factory, settings, make_runner, monkeypatch):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    fail_replace_once(monkeypatch, dst_name="fontline-vi.pdf", src_name=".previous")  # bước 3 (.previous → versions/<vid>/) hỏng
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no, row.rebuild_error) == ("done", "fontline-vi.pdf", 1, "Lỗi nội bộ (OSError).")
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "fontline-en.pdf").exists()
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []


def fail_commit_inside_commit_swap(runner, monkeypatch) -> list:
    """Giao dịch THẬT của _commit_swap (UPDATE + INSERT + tỉa đã chạy) hỏng đúng lúc commit. Trả danh sách version_no mà
    giao dịch nhìn thấy ngay trước commit — chứng minh lỗi xảy ra SAU INSERT + tỉa, không phải trước."""
    real_swap, real_sessions, seen = runner._commit_swap, runner._sessions, []

    def failing_sessions():
        db = real_sessions()

        def commit():
            seen.append(sorted(db.scalars(select(FileVersion.version_no)).all()))
            raise RuntimeError("disk I/O error")

        db.commit = commit
        return db

    def swap(*args, **kwargs):
        runner._sessions = failing_sessions  # chỉ trong lời gọi này (một luồng chạy job)
        try:
            return real_swap(*args, **kwargs)
        finally:
            runner._sessions = real_sessions

    monkeypatch.setattr(runner, "_commit_swap", swap)
    return seen


def test_a_failed_commit_after_insert_and_prune_rolls_back_the_whole_swap(factory, settings, make_runner, monkeypatch):
    set_max_versions(factory, 2)  # giữ 1 bản cũ: lượt này chèn bản 3 và tỉa cả bản 1 lẫn 2 — trong giao dịch
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    first = seed_version(factory, directory, file_id, version_no=1, output_name="archived-1.pdf")
    second = seed_version(factory, directory, file_id, version_no=2, output_name="archived-2.pdf")
    with factory() as db:
        row = db.get(File, file_id)
        row.config, row.retranslate_config = SIMPLE, ACADEMIC
        db.commit()
    runner = make_runner()
    seen = fail_commit_inside_commit_swap(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert seen == [[3]]  # trước commit: bản 3 đã chèn, bản 1 + 2 đã tỉa
    assert (row.status, row.output_name, row.language, row.engine, row.version_no, row.config, row.retranslate_config) == (
        "done", "fontline-vi.pdf", "vi", "google_free", 3, SIMPLE, None)
    assert row.rebuild_error == "Lỗi nội bộ (RuntimeError)."
    assert [(version.id, version.version_no) for version in versions_of(factory, file_id)] == [(first, 1), (second, 2)]
    assert version_dirs(directory) == sorted([first, second])  # thư mục versions/<vid>/ của lượt hỏng đã gỡ, kho cũ nguyên
    assert (directory / "versions" / first / "archived-1.pdf").read_bytes() == b"archived v1"
    assert (directory / "versions" / second / "archived-2.pdf").read_bytes() == b"archived v1"
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "fontline-en.pdf").exists() and not (directory / "rebuild").exists()

def test_a_database_failure_with_the_same_output_name_also_puts_the_old_translation_back(factory, settings, make_runner, monkeypatch):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="vi")  # tên mới == tên cũ
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    fail_commit_swap(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no) == ("done", "fontline-vi.pdf", 1)
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"  # DB và đĩa cùng nói "bản cũ"
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []


def test_a_swap_whose_row_was_recovered_elsewhere_puts_the_archived_file_back(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en", status="queued")  # runner khác đã phục hồi dòng
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "rebuild").mkdir()
    (directory / "rebuild" / "fontline-en.pdf").write_bytes(b"new render")
    previous = Previous("fontline-vi.pdf", "vi", "google_free", None, "auto", "sans", 2, None, None, 1)
    make_runner()._finish_rebuild(file_id, "u1", "serif", "fontline-vi.pdf", retranslate=("en", "google_free", "", None), message="Xong",
                                  output_name="fontline-en.pdf", untranslated=0, font_used="serif", previous=previous, max_versions=3)
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"  # bản cũ về đúng chỗ, bản mới đã chép vào bị gỡ
    assert not (directory / "fontline-en.pdf").exists()
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []
    with factory() as db:
        row = db.get(File, file_id)
        assert (row.status, row.version_no, row.retranslate_language) == ("queued", 1, "en")


def test_staging_rescues_an_orphan_version_folder_holding_the_missing_current_output(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    orphan = directory / "versions" / "deadbeef0001"  # chết giữa bước 3 và 4: bản cũ đã sang kho, DB chưa commit → không có dòng
    orphan.mkdir(parents=True)
    (directory / "fontline-vi.pdf").replace(orphan / "fontline-vi.pdf")
    make_runner()._staging(directory, "fontline-vi.pdf", known_versions=frozenset())
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not orphan.exists()


def test_staging_deletes_an_orphan_version_folder_when_the_current_output_is_present_and_keeps_known_ones(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "versions" / "known0000001").mkdir(parents=True)
    (directory / "versions" / "known0000001" / "fontline-en.pdf").write_bytes(b"v")
    (directory / "versions" / "orphan000001").mkdir()
    (directory / "versions" / "orphan000001" / "fontline-vi.pdf").write_bytes(b"pruned")  # tỉa đã commit, rmtree chưa kịp
    make_runner()._staging(directory, "fontline-vi.pdf", known_versions=frozenset({"known0000001"}))
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"  # bản hiện tại không bị bản mồ côi đè
    assert (directory / "versions" / "known0000001" / "fontline-en.pdf").is_file()
    assert not (directory / "versions" / "orphan000001").exists()


def test_recovery_after_a_crash_between_archive_and_commit_ends_with_exactly_one_version(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en", status="running")
    with factory() as db:
        db.get(File, file_id).retranslate_config = ACADEMIC  # _recover giữ snapshot đang đỗ cùng retranslate_*
        db.commit()
    directory = file_dir(settings.users_dir, "u1", file_id)
    orphan = directory / "versions" / "deadbeef0001"
    orphan.mkdir(parents=True)
    (directory / "fontline-vi.pdf").replace(orphan / "fontline-vi.pdf")  # bản cũ chỉ còn trong thư mục mồ côi
    (directory / "rebuild").mkdir()
    (directory / "rebuild" / "fontline-en.pdf").write_bytes(b"ban moi do dang")
    make_runner().start()  # _recover: running → queued, chạy lại lượt dịch lại; _staging cứu bản cũ về trước khi worker chạy
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no, row.language) == ("done", "fontline-en.pdf", 2, "en")
    assert (row.config, row.retranslate_config) == (ACADEMIC, None)
    [version] = versions_of(factory, file_id)
    assert version.config is None and version.output_name == "fontline-vi.pdf"
    assert (directory / "versions" / version.id / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    wait_gone(directory / "rebuild")
    assert version_dirs(directory) == [version.id]  # thư mục mồ côi đã dọn, chỉ còn bản được ghi nhận
    assert (directory / "fontline-en.pdf").read_bytes().endswith(b"% rebuilt font=serif\n")


@pytest.mark.parametrize("failure", ["missing_key", "unknown_engine", "no_handoff_worker"])
def test_a_rerun_that_fails_before_staging_still_rescues_the_old_translation_from_an_orphan_version(
        factory, settings, make_runner, failure):
    """Chết giữa bước 3 và 4 (bản cũ chỉ còn trong versions/<x>/ mồ côi), rồi lượt chạy lại hỏng TRƯỚC _staging: bản cũ vẫn phải
    về thư mục job — không thì tệp trở lại `done` mà tải xuống trả 410."""
    if failure == "no_handoff_worker":
        add_credential(factory, settings, "gemini")
    engine = "nope" if failure == "unknown_engine" else "gemini"
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en", engine=engine, model="gemini-3.5-flash-lite",
                              status="running")
    directory = file_dir(settings.users_dir, "u1", file_id)
    orphan = directory / "versions" / "deadbeef0001"
    orphan.mkdir(parents=True)
    (directory / "fontline-vi.pdf").replace(orphan / "fontline-vi.pdf")
    make_runner(**({"handoff_worker_cmd": ()} if failure == "no_handoff_worker" else {})).start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.version_no, row.retranslate_language) == ("done", "fontline-vi.pdf", "vi", 1, None)
    assert row.rebuild_error == {
        "missing_key": MISSING_KEY_MESSAGE.format(provider="Gemini (Google AI Studio)"),
        "unknown_engine": "Engine dịch không được hỗ trợ: nope",
        "no_handoff_worker": NO_HANDOFF_WORKER_MESSAGE,
    }[failure]
    path, _ = download_target(settings, row, "translated")  # đúng đường tải xuống: không 410
    assert path == directory / "fontline-vi.pdf" and path.read_bytes() == PDF + b"old translation"
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []


def test_a_stranded_backup_wins_over_a_stale_orphan_with_the_same_name_when_the_rerun_fails_early(factory, settings, make_runner):
    """Hai sự cố chồng nhau: chết giữa bước 1 và 2 (bản hiện tại chỉ còn ở rebuild/.previous) VÀ một thư mục kho mồ côi cũ
    (tỉa xong chưa kịp xoá) mang cùng tên; lượt chạy lại hỏng sớm (thiếu key). .previous là bản thật — phải thắng."""
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en", engine="gemini", model="gemini-3.5-flash-lite",
                              status="running")  # không có credential
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "rebuild").mkdir()
    (directory / "fontline-vi.pdf").replace(directory / "rebuild" / ".previous")
    (directory / "versions" / "orphan000001").mkdir(parents=True)
    (directory / "versions" / "orphan000001" / "fontline-vi.pdf").write_bytes(b"stale pruned version")
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no) == ("done", "fontline-vi.pdf", 1)
    assert row.rebuild_error == MISSING_KEY_MESSAGE.format(provider="Gemini (Google AI Studio)")
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert version_dirs(directory) == [] and not (directory / "rebuild").exists()


# ---- Giờ của bản dịch (spec 2026-10-15 §4) ---------------------------------------------------------------------


def stamp(factory, file_id, **values) -> None:
    """Đặt vài cột của dòng files thẳng DB (trạng thái "đã có từ trước" của một tệp)."""
    with factory() as db:
        row = db.get(File, file_id)
        for name, value in values.items():
            setattr(row, name, value)
        db.commit()


def test_translated_at_is_set_when_a_translation_finishes(factory, settings, make_runner):
    row = run_one(factory, settings, make_runner, "doc.pdf")
    assert row.status == "done" and row.translated_at is not None and row.translated_at == row.finished_at


def test_a_font_rebuild_keeps_translated_at_while_a_retranslate_moves_it(factory, settings, make_runner):
    file_id = add_translated(factory, settings, "fontline.pdf", rebuild_font="serif")
    before = utcnow() - timedelta(days=1)
    stamp(factory, file_id, translated_at=before)
    runner = make_runner()
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.font, row.translated_at) == ("done", "serif", before)  # dựng lại font: cùng bản dịch, giờ dịch không đổi
    assert row.finished_at is not None and row.finished_at > before
    requeue_retranslate(factory, file_id, language="en")
    runner.enqueue(file_id)
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no) == ("done", 2) and row.translated_at == row.finished_at and row.translated_at > before
    [version] = versions_of(factory, file_id)
    assert version.translated_at == before and version.restored_from is None  # bản cũ mang giờ dịch của chính nó


def test_an_archived_version_keeps_restored_from_and_a_fresh_retranslate_clears_it(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    stamp(factory, file_id, restored_from=1, translated_at=utcnow() - timedelta(hours=1))
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no, row.restored_from) == ("done", 2, None)  # bản dịch mới không "khôi phục từ" gì
    [version] = versions_of(factory, file_id)
    assert version.restored_from == 1 and version.translated_at is not None


# ---- Bảng đoạn đi theo phiên bản (spec 2026-10-15 §3) ----------------------------------------------------------


def test_a_retranslate_copies_the_old_segment_table_into_the_version_store_and_the_new_one_into_the_job(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id = add_retranslate(factory, settings, "newtable.pdf", language="en", engine="gemini", model="gemini-3.8-flash", font="sans")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no) == ("done", 2)
    [version] = versions_of(factory, file_id)
    store = directory / "versions" / version.id
    assert (store / "segments.jsonl").read_text(encoding="utf-8") == "old\n"  # BẢN SAO của bảng cũ đi theo bản cũ
    assert (store / "segments.meta.json").read_text(encoding="utf-8") == "meta\n"
    assert (store / "newtable-vi.pdf").is_file()
    wait_gone(directory / "rebuild")  # thay bảng chạy SAU commit
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "x", "dst": "y"}\n'  # bảng mới ở thư mục job
    assert (directory / "newtable-en.pdf").is_file()


def test_a_version_of_a_plain_engine_file_has_no_table_to_carry(factory, settings, make_runner):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    for name in ("segments.jsonl", "segments.meta.json"):
        (directory / name).unlink()  # tệp Google miễn phí thật không có bảng đoạn (add_retranslate gieo bảng giả — bỏ đi)
    make_runner().start()
    assert wait_row(factory, file_id).status == "done"
    [version] = versions_of(factory, file_id)
    assert not (directory / "versions" / version.id / "segments.jsonl").exists()
    wait_gone(directory / "rebuild")
    assert not (directory / "segments.jsonl").exists()


def test_a_database_failure_after_archiving_removes_the_copied_tables_with_the_version_folder(factory, settings, make_runner, monkeypatch):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    fail_commit_swap(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no, row.rebuild_error) == ("done", 1, "Lỗi nội bộ (RuntimeError).")
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []  # _put_back rmtree cả thư mục kho (kèm bản sao bảng)
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"  # bảng job (bản gốc) nguyên
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == "meta\n"
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"


def fail_table_copy_into_the_store(monkeypatch):
    """shutil.copyfile lỗi (hết đĩa) đúng khi đích nằm trong versions/<vid>/ — bước chép bảng của _finish_rebuild."""
    from app.engine import jobs
    real = jobs.shutil.copyfile

    def copyfile(src, dst, *args, **kwargs):
        if Path(dst).parent.parent.name == "versions":
            raise OSError(28, "No space left on device")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(jobs.shutil, "copyfile", copyfile)


def test_a_failed_table_copy_puts_the_old_translation_back_like_a_database_failure(factory, settings, make_runner, monkeypatch):
    file_id = add_retranslate(factory, settings, "fontline.pdf", language="en")
    directory = file_dir(settings.users_dir, "u1", file_id)
    fail_table_copy_into_the_store(monkeypatch)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no, row.rebuild_error) == ("done", "fontline-vi.pdf", 1, "Lỗi nội bộ (OSError).")
    assert (directory / "fontline-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "fontline-en.pdf").exists() and not (directory / "rebuild").exists()
    assert versions_of(factory, file_id) == [] and version_dirs(directory) == []
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"


# ---- Khôi phục bản cũ (spec 2026-10-15 §2) -----------------------------------------------------------------------


def add_restore(factory, settings, filename="doc.pdf", *, status="queued", with_tables=True, src_engine="gemini",
                src_model="gemini-3.5-flash-lite", src_config=ACADEMIC) -> tuple[str, str]:
    """Tệp đã xong (Bản 2 = bản hiện tại: PDF "old translation", bảng "old"/"meta", google_free, snapshot SIMPLE) có Bản 1 trong kho
    (PDF "archived v1", tiếng Anh, `src_engine`/`src_model`, snapshot `src_config`, font serif, 7 đoạn chưa dịch, bảng "v1" + meta THẬT
    của lựa chọn đó khi `with_tables`) vừa được yêu cầu khôi phục Bản 1 — đúng UPDATE của files.service.restore_version. Trả (file_id, version_id)."""
    file_id = add_translated(factory, settings, filename, rebuild_font="serif", status="done")
    directory = file_dir(settings.users_dir, "u1", file_id)
    seed_tables(directory)
    version_id = seed_version(factory, directory, file_id, version_no=1, output_name=f"{Path(filename).stem}-en.pdf")
    if with_tables:
        (directory / "versions" / version_id / "segments.jsonl").write_text('{"src": "v1", "dst": "V1"}\n', encoding="utf-8")
        meta = handoff_meta(ENGINE_BY_ID[src_engine].provider, src_model, "en", src_config)  # như handoff_worker.run đã ghi cho Bản 1
        (directory / "versions" / version_id / "segments.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    with factory() as db:
        version = db.get(FileVersion, version_id)
        version.engine, version.model, version.config, version.font, version.font_used, version.untranslated = (
            src_engine, src_model, src_config, "serif", "serif", 7)
        version.translated_at = utcnow() - timedelta(days=2)
        row = db.get(File, file_id)
        row.config, row.translated_at = SIMPLE, utcnow() - timedelta(days=1)
        row.restore_version, row.rebuild_font = version_id, "serif"
        row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.retranslate_config = "en", src_engine, src_model, src_config
        row.status, row.done_pages, row.total_pages, row.message, row.stage = status, 0, 0, "", ""
        db.commit()
    return file_id, version_id


def handoff_meta(provider: str, model: str | None, language: str, config: str | None) -> dict:
    """segments.meta.json đúng như handoff_worker.run ghi cho lựa chọn này: chỉ dẫn là chuỗi runner dựng từ snapshot (jobs.py), lưu sha256."""
    return {"provider": provider, "model": model, "target_language": language,
            "instructions": instructions_digest(build_instructions(load_snapshot(config), language))}


def record_replaces(monkeypatch) -> list[tuple[Path, Path]]:
    """Ghi lại mọi os.replace (nguồn, đích) — chứng minh một bước đổi tên THẬT SỰ đã chạy, không chỉ là kết quả trông giống."""
    from app.engine import jobs
    real, calls = jobs.os.replace, []

    def replace(src, dst, *args, **kwargs):
        calls.append((Path(src), Path(dst)))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(jobs.os, "replace", replace)
    return calls


def test_restoring_a_version_copies_it_into_place_without_a_worker_or_a_key_and_archives_the_current_one(
        factory, settings, make_runner, monkeypatch):
    file_id, version_id = add_restore(factory, settings, "doc.pdf")  # bản nguồn Gemini, KHÔNG có credential nào
    directory = file_dir(settings.users_dir, "u1", file_id)
    replaces = record_replaces(monkeypatch)
    runner = make_runner()
    ran = processed_by(runner)
    runner.start()
    row = wait_row(factory, file_id)
    assert ran == [] and not (directory / "env-seen.json").exists()  # không worker nào chạy, không cần key
    assert (row.status, row.message, row.output_name, row.language, row.engine, row.model) == (
        "done", "Xong", "doc-en.pdf", "en", "gemini", "gemini-3.5-flash-lite")
    assert (row.font, row.font_used, row.untranslated, row.config, row.version_no, row.restored_from) == ("serif", "serif", 7, ACADEMIC, 3, 1)
    assert (row.restore_version, row.retranslate_language, row.retranslate_engine, row.retranslate_model, row.retranslate_config,
            row.rebuild_font, row.rebuild_error) == (None, None, None, None, None, None, "")
    assert row.translated_at == row.finished_at
    assert (directory / "doc-en.pdf").read_bytes() == b"archived v1"
    # Bản sao vào rebuild/ qua .tmp rồi MỘT phép đổi tên: chết giữa lúc chép không để lại tệp cụt mang tên kết quả.
    assert (directory / "rebuild" / "doc-en.pdf.tmp", directory / "rebuild" / "doc-en.pdf") in replaces
    source, archived = versions_of(factory, file_id)
    assert source.id == version_id and (directory / "versions" / version_id / "doc-en.pdf").read_bytes() == b"archived v1"  # nguồn nguyên
    assert (archived.version_no, archived.language, archived.engine, archived.config, archived.output_name, archived.restored_from) == (
        2, "vi", "google_free", SIMPLE, "doc-vi.pdf", None)
    assert archived.translated_at is not None and archived.translated_at < row.translated_at
    assert (directory / "versions" / archived.id / "doc-vi.pdf").read_bytes() == PDF + b"old translation"
    assert (directory / "versions" / archived.id / "segments.jsonl").read_text(encoding="utf-8") == "old\n"  # bảng cũ đi theo bản bị thay
    wait_gone(directory / "rebuild")
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "v1", "dst": "V1"}\n'  # bảng của nguồn ở thư mục job
    assert (directory / "segments.meta.json").read_text(encoding="utf-8") == (
        directory / "versions" / version_id / "segments.meta.json").read_text(encoding="utf-8")
    assert (directory / "versions" / version_id / "segments.jsonl").is_file()  # CHÉP bảng nguồn, không chuyển
    assert not (directory / "doc-vi.pdf").exists()


def test_restoring_a_version_without_a_table_drops_the_job_table(factory, settings, make_runner):
    file_id, _version_id = add_restore(factory, settings, "doc.pdf", with_tables=False, src_engine="google_free", src_model=None, src_config=None)
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.engine, row.config, row.version_no) == ("done", "google_free", None, 3)
    wait_gone(directory / "rebuild")
    assert not (directory / "segments.jsonl").exists() and not (directory / "segments.meta.json").exists()
    _source, archived = versions_of(factory, file_id)
    assert (directory / "versions" / archived.id / "segments.jsonl").read_text(encoding="utf-8") == "old\n"


def test_a_font_rebuild_right_after_a_restore_reuses_the_restored_table_without_calling_the_api(factory, settings, make_runner):
    add_credential(factory, settings, "gemini")
    file_id, _version_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    runner.start()
    assert wait_row(factory, file_id).version_no == 3
    wait_gone(directory / "rebuild")
    with factory() as db:  # như files.service.rebuild_file
        row = db.get(File, file_id)
        row.status, row.rebuild_font, row.rebuild_error, row.message = "queued", "sans", "", ""
        db.commit()
    restored_meta = json.loads((directory / "segments.meta.json").read_text(encoding="utf-8"))  # meta của bảng bản nguồn, đã chép về
    assert restored_meta == handoff_meta("gemini", "gemini-3.5-flash-lite", "en", ACADEMIC)
    runner.enqueue(file_id)
    row = wait_row(factory, file_id)
    assert (row.status, row.font, row.version_no, row.config) == ("done", "sans", 3, ACADEMIC)
    seen = env_seen(settings, file_id)
    assert seen["table_seen"] is True and seen["provider"] == "gemini" and HEADER in seen["instructions"]  # bảng + chỉ dẫn của bản khôi phục
    # Lựa chọn worker nhận cho lượt dựng lại == meta của bảng → _resume thật dùng lại cả bảng, không đoạn nào phải gọi nhà cung cấp.
    worker_meta = {"provider": seen["provider"], "model": seen["model"], "target_language": seen["argv"][2],
                   "instructions": instructions_digest(seen["instructions"])}
    assert worker_meta == restored_meta
    assert seen["meta_matches"] is True  # cùng phép so của _resume, trên meta thật nằm trong rebuild/


@pytest.mark.parametrize("missing", ["file", "row"])
def test_restoring_when_the_source_is_gone_aborts_and_keeps_the_current_translation(factory, settings, make_runner, missing):
    file_id, version_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    if missing == "file":
        (directory / "versions" / version_id / "doc-en.pdf").unlink()
    else:
        with factory() as db:
            db.execute(delete(FileVersion).where(FileVersion.id == version_id))
            db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.version_no, row.restored_from) == ("done", "doc-vi.pdf", "vi", 2, None)
    assert row.rebuild_error == RESTORE_SOURCE_MISSING_MESSAGE
    assert (row.restore_version, row.retranslate_language, row.rebuild_font, row.config) == (None, None, None, SIMPLE)
    assert (directory / "doc-vi.pdf").read_bytes() == PDF + b"old translation" and not (directory / "rebuild").exists()
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"
    assert [version.id for version in versions_of(factory, file_id)] == ([version_id] if missing == "file" else [])
    assert version_dirs(directory) == ([version_id] if missing == "file" else [])  # dòng mất → thư mục thành mồ côi, bị dọn


def test_a_failed_rename_of_the_copied_source_aborts_the_restore_without_leaving_a_partial_file(factory, settings, make_runner, monkeypatch):
    file_id, version_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    fail_replace_once(monkeypatch, dst_name="doc-en.pdf", src_name="doc-en.pdf.tmp")  # đã chép xong .tmp, đổi tên hỏng (hết đĩa)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.version_no, row.restored_from, row.config) == (
        "done", "doc-vi.pdf", "vi", 2, None, SIMPLE)
    assert (row.rebuild_error, row.restore_version, row.retranslate_language, row.rebuild_font) == ("Lỗi nội bộ (OSError).", None, None, None)
    assert (directory / "doc-vi.pdf").read_bytes() == PDF + b"old translation"
    assert not (directory / "doc-en.pdf").exists() and not (directory / "rebuild").exists()  # .tmp đi theo rebuild/
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"
    assert [version.id for version in versions_of(factory, file_id)] == [version_id] and version_dirs(directory) == [version_id]
    assert (directory / "versions" / version_id / "doc-en.pdf").read_bytes() == b"archived v1"


def test_restoring_the_oldest_version_at_the_limit_prunes_the_source_only_after_the_copy_is_in_place(factory, settings, make_runner):
    set_max_versions(factory, 2)  # hiện tại + 1 bản cũ
    file_id, version_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.version_no, row.restored_from) == ("done", 3, 1)
    assert (directory / "doc-en.pdf").read_bytes() == b"archived v1"  # bản sao đã là bản hiện tại
    [archived] = versions_of(factory, file_id)
    assert archived.version_no == 2  # Bản 1 (nguồn) là bản cũ nhất vượt hạn → bị tỉa trong cùng giao dịch
    wait_gone(directory / "rebuild")
    assert version_dirs(directory) == [archived.id] and version_id not in version_dirs(directory)


def test_stale_segment_tables_left_in_rebuild_are_dropped_before_a_restore_copies_the_source(factory, settings, make_runner):
    file_id, _version_id = add_restore(factory, settings, "doc.pdf", with_tables=False)
    directory = file_dir(settings.users_dir, "u1", file_id)
    (directory / "rebuild").mkdir()
    for name in ("segments.jsonl", "segments.meta.json"):
        (directory / "rebuild" / name).write_text("stale\n", encoding="utf-8")  # một lượt dịch lại bị ngắt để lại; _staging cố ý giữ
    make_runner().start()
    assert wait_row(factory, file_id).version_no == 3
    wait_gone(directory / "rebuild")
    assert not (directory / "segments.jsonl").exists()  # không phải bảng của bản nguồn → không được theo vào thư mục job


def test_a_database_failure_during_a_restore_puts_the_current_translation_back(factory, settings, make_runner, monkeypatch):
    file_id, version_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    fail_commit_swap(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.language, row.version_no, row.restored_from, row.config) == (
        "done", "doc-vi.pdf", "vi", 2, None, SIMPLE)
    assert row.rebuild_error == "Lỗi nội bộ (RuntimeError)." and row.restore_version is None
    assert (directory / "doc-vi.pdf").read_bytes() == PDF + b"old translation" and not (directory / "doc-en.pdf").exists()
    assert not (directory / "rebuild").exists() and (directory / "segments.jsonl").read_text(encoding="utf-8") == "old\n"
    assert [version.id for version in versions_of(factory, file_id)] == [version_id] and version_dirs(directory) == [version_id]


def test_a_failed_commit_during_a_restore_rolls_back_the_whole_swap(factory, settings, make_runner, monkeypatch):
    set_max_versions(factory, 2)
    file_id, version_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    runner = make_runner()
    seen = fail_commit_inside_commit_swap(runner, monkeypatch)
    runner.start()
    row = wait_row(factory, file_id)
    assert seen == [[2]]  # trước commit: Bản 2 đã chèn, Bản 1 (nguồn, vượt hạn) đã tỉa — rồi commit hỏng
    assert (row.status, row.output_name, row.version_no, row.restored_from) == ("done", "doc-vi.pdf", 2, None)
    assert [version.id for version in versions_of(factory, file_id)] == [version_id]  # rollback: nguồn còn, Bản 2 không có
    assert version_dirs(directory) == [version_id] and (directory / "versions" / version_id / "doc-en.pdf").read_bytes() == b"archived v1"
    assert (directory / "doc-vi.pdf").read_bytes() == PDF + b"old translation" and not (directory / "doc-en.pdf").exists()


def test_recovery_reruns_an_interrupted_restore_and_ends_with_the_source_intact_and_one_new_version(factory, settings, make_runner):
    file_id, version_id = add_restore(factory, settings, "doc.pdf", status="running")  # chết giữa bước 3 và 4 của lượt khôi phục
    directory = file_dir(settings.users_dir, "u1", file_id)
    orphan = directory / "versions" / "deadbeef0001"
    orphan.mkdir(parents=True)
    (directory / "doc-vi.pdf").replace(orphan / "doc-vi.pdf")  # bản hiện tại chỉ còn trong thư mục mồ côi
    (directory / "rebuild").mkdir()
    (directory / "rebuild" / "doc-en.pdf.tmp").write_bytes(b"chep do dang")
    make_runner().start()  # _recover: running → queued (giữ restore_version + retranslate_*), chạy lại từ đầu
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no, row.restored_from) == ("done", "doc-en.pdf", 3, 1)
    assert (directory / "doc-en.pdf").read_bytes() == b"archived v1"
    source, archived = versions_of(factory, file_id)
    assert source.id == version_id and archived.output_name == "doc-vi.pdf"
    assert (directory / "versions" / archived.id / "doc-vi.pdf").read_bytes() == PDF + b"old translation"
    wait_gone(directory / "rebuild")
    assert version_dirs(directory) == sorted([version_id, archived.id])  # thư mục mồ côi đã dọn, tệp .tmp không còn


def test_a_restore_rerun_that_finds_the_source_missing_still_rescues_the_current_translation_from_an_orphan(factory, settings, make_runner):
    file_id, version_id = add_restore(factory, settings, "doc.pdf", status="running")
    directory = file_dir(settings.users_dir, "u1", file_id)
    orphan = directory / "versions" / "deadbeef0001"
    orphan.mkdir(parents=True)
    (directory / "doc-vi.pdf").replace(orphan / "doc-vi.pdf")
    (directory / "versions" / version_id / "doc-en.pdf").unlink()  # tệp nguồn mất đúng lúc này
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.output_name, row.version_no, row.rebuild_error) == ("done", "doc-vi.pdf", 2, RESTORE_SOURCE_MISSING_MESSAGE)
    path, _ = download_target(settings, row, "translated")  # đúng đường tải xuống: không 410
    assert path == directory / "doc-vi.pdf" and path.read_bytes() == PDF + b"old translation"
    assert [version.id for version in versions_of(factory, file_id)] == [version_id] and version_dirs(directory) == [version_id]


def test_a_font_rebuild_after_a_restore_that_died_past_its_commit_cleans_up_and_keeps_both_versions(factory, settings, make_runner):
    """Chết giữa bước 4 và 6 của lượt khôi phục (spec 2026-10-15 §2 (c)–(d)): giao dịch đã commit — Bản 3 là bản sao của Bản 1,
    Bản 2 vào kho, một bản vượt hạn đã mất dòng — nhưng thư mục của bản đã tỉa chưa xoá và rebuild/ còn bảng của bản nguồn (bảng
    thư mục job chưa thay: §2 (d), không kiểm ở đây). Lượt dựng lại font kế tiếp: _staging dọn thư mục mồ côi, kho có dòng nguyên."""
    add_credential(factory, settings, "gemini")
    file_id, source_id = add_restore(factory, settings, "doc.pdf")
    directory = file_dir(settings.users_dir, "u1", file_id)
    store = directory / "versions"
    archived_id = "archived0002"
    (store / archived_id).mkdir()
    (directory / "doc-vi.pdf").replace(store / archived_id / "doc-vi.pdf")  # bước 3: bản hiện tại cũ (+ bảng của nó) vào kho
    for name in ("segments.jsonl", "segments.meta.json"):
        (store / archived_id / name).write_bytes((directory / name).read_bytes())
    (directory / "doc-en.pdf").write_bytes((store / source_id / "doc-en.pdf").read_bytes())  # bước 2: bản sao đã vào chỗ
    (directory / "rebuild").mkdir()
    for name in ("segments.jsonl", "segments.meta.json"):
        (directory / "rebuild" / name).write_bytes((store / source_id / name).read_bytes())  # chờ _replace_tables sau commit
    (store / "orphan000001").mkdir()
    (store / "orphan000001" / "doc-old.pdf").write_bytes(b"pruned")  # dòng đã tỉa trong giao dịch, rmtree chưa kịp
    with factory() as db:
        db.add(FileVersion(id=archived_id, file_id=file_id, version_no=2, language="vi", engine="google_free", font="auto",
                           font_used="sans", config=SIMPLE, output_name="doc-vi.pdf", untranslated=2, archived_at=utcnow()))
        row = db.get(File, file_id)  # giá trị mà giao dịch của lượt khôi phục đã ghi, rồi người dùng bấm dựng lại font
        row.output_name, row.language, row.engine, row.model, row.font, row.font_used, row.untranslated, row.config = (
            "doc-en.pdf", "en", "gemini", "gemini-3.5-flash-lite", "serif", "serif", 7, ACADEMIC)
        row.version_no, row.restored_from, row.restore_version, row.rebuild_font = 3, 1, None, "sans"
        row.retranslate_language = row.retranslate_engine = row.retranslate_model = row.retranslate_config = None
        db.commit()
    make_runner().start()
    row = wait_row(factory, file_id)
    assert (row.status, row.rebuild_error, row.output_name, row.font, row.version_no, row.restored_from) == (
        "done", "", "doc-en.pdf", "sans", 3, 1)  # dựng lại font: cùng bản dịch, vẫn "khôi phục từ Bản 1"
    assert not (store / "orphan000001").exists()
    assert [(version.id, version.version_no) for version in versions_of(factory, file_id)] == [(source_id, 1), (archived_id, 2)]
    assert version_dirs(directory) == sorted([source_id, archived_id])
    assert (store / source_id / "doc-en.pdf").read_bytes() == b"archived v1"
    assert (store / archived_id / "doc-vi.pdf").read_bytes() == PDF + b"old translation"
    assert (store / archived_id / "segments.jsonl").read_text(encoding="utf-8") == "old\n"
    wait_gone(directory / "rebuild")
    assert (directory / "doc-en.pdf").read_bytes().endswith(b"% rebuilt font=sans\n")


def test_recovery_keeps_the_restore_request(factory, settings, make_runner):
    file_id, version_id = add_restore(factory, settings, "doc.pdf", status="running")
    make_runner()._recover()
    with factory() as db:
        row = db.get(File, file_id)
        assert (row.status, row.restore_version, row.retranslate_language, row.rebuild_font) == ("queued", version_id, "en", "serif")
