"""Hàng đợi dịch: DB chính là hàng đợi, việc nặng chạy ở tiến trình con.

Tách tiến trình vì nhân dịch kéo theo onnxruntime, OpenCV, PyMuPDF — segfault trong
đó mà chạy chung tiến trình web là sập cả máy chủ. Khác bản vi-translate: không có
hàng đợi trong RAM — luồng chạy tự nhận dòng `queued` cũ nhất trong DB, nên restart
không mất việc, và dòng do tiến trình khác thêm vào cũng được nhận.

Mỗi thư mục dữ liệu chỉ một runner chạy việc: runner phải giữ `flock` trên
`<data_dir>/runner.lock`. Hai container cùng gắn /data (vd lúc Coolify deploy chồng)
thì container sau chỉ phục vụ web, cứ vài giây thử lấy khoá; container trước dừng là
nó tiếp quản (phục hồi job dở rồi chạy tiếp).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import sessionmaker

from ..db import utcnow
from ..models import File, FileVersion
from ..profiles.prompt import build_instructions
from ..profiles.snapshot import load as load_snapshot
from ..providers.catalog import ENGINE_BY_ID, PROVIDER_LABELS
from ..providers.credentials import drop_gemini_model, load_api_key
from ..system.store import effective_max_versions
from .paths import file_dir, safe_name

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger("engine")

PROGRESS_WRITE_STEP = 5  # % — tiến độ chi tiết giữ trong RAM, DB chỉ ghi mỗi 5%
MESSAGE_LIMIT = 1000
STOP_JOIN_SECONDS = 10
KNOWN_STAGES = {"split", "translate", "render"}  # stage lạ (worker hỏng/giả) → "" chứ không lưu nguyên văn
SENSITIVE_ENV_KEYS = {"SECRET_KEY", "SMTP_PASSWORD", "SETUP_TOKEN"}  # không lọt vào env của worker (cả hai loại)
REBUILD_DIR = "rebuild"  # dựng lại chạy trong thư mục con: bản dịch cũ ở thư mục job còn nguyên tới khi thay
TABLE_FILES = ("segments.jsonl", "segments.meta.json")  # bảng đoạn đã dịch (đã trả tiền) của worker handoff
BACKUP_NAME = ".previous"  # bản dịch cũ cất tạm trong rebuild/ lúc thay — cũng không được là tên tệp kết quả
ERROR_LOG_NAME = "worker-stderr.log"  # stderr của worker — không được là tên tệp kết quả
VERSIONS_DIR = "versions"  # kho bản cũ versions/<version_id>/<output_name> (spec 2026-10-14 §5) — tách khỏi rebuild/
FONT_PROFILES = {"sans", "serif"}  # giá trị hợp lệ của dòng {"font"} — giá trị lạ không được lưu
STAGE_MESSAGES = {
    "": "Đang dịch…",
    "split": "Bước 1/3: Đang tách đoạn văn…",
    "translate": "Bước 2/3: Đang dịch bằng {engine}…",
    "render": "Bước 3/3: Đang dựng PDF…",
}
MISSING_KEY_MESSAGE = "Chưa có API key cho {provider}. Thêm key trong Cài đặt rồi bấm Dịch lại."
NO_HANDOFF_WORKER_MESSAGE = "Thiếu cấu hình worker dịch qua API."
MODEL_DROPPED_NOTE = " Đã gỡ model khỏi danh sách của key; model mặc định hiện là {label}."
RESTORE_SOURCE_MISSING_MESSAGE = "Không tìm thấy tệp của bản cũ cần khôi phục."  # khôi phục mà bản nguồn (dòng / tệp) không còn


@dataclass
class Progress:
    done: int = 0
    total: int = 0
    written_pct: int = -100
    stage: str = ""  # split|translate|render — "" với google_free
    engine_label: str = ""


@dataclass(frozen=True)
class Previous:
    """Metadata của bản dịch ĐANG là bản chính — đọc trong _finish trước khi _finish_rebuild ghi đè dòng files (spec 2026-10-14 §5).
    finished_at thường None (_claim_next đã xoá); UI dùng archived_at. translated_at/restored_from (spec 2026-10-15 §4) đi theo bản
    khi cất."""

    output_name: str | None
    language: str
    engine: str
    model: str | None
    font: str
    font_used: str | None
    untranslated: int
    finished_at: datetime | None
    config: str | None
    version_no: int
    translated_at: datetime | None = None
    restored_from: int | None = None


@dataclass(frozen=True)
class RestoreSource:
    """Bản nguồn của một lượt khôi phục (spec 2026-10-15 §2) — đọc từ dòng file_versions trong _execute, trước mọi lối thoát sớm."""

    store: Path  # <file_dir>/versions/<vid>/
    output_name: str
    untranslated: int
    font_used: str | None


def _pct(done: int, total: int) -> int:
    return int(done * 100 / total) if total else 0


def _minutes(seconds: float) -> int:
    return max(1, round(seconds / 60))


def _table_lines(path: Path) -> list[str] | None:
    """Các dòng nguyên vẹn (có xuống dòng cuối) của bảng đoạn mà là bản ghi {"src","dst"} hợp lệ; None nếu đọc lỗi."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    lines = []
    for line in text.splitlines(keepends=True):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if line.endswith("\n") and isinstance(record, dict) and isinstance(record.get("src"), str) \
                and isinstance(record.get("dst"), str):
            lines.append(line)
    return lines


def _extends(current: Path, staged: Path) -> bool:
    """Bảng trong rebuild/ có giữ được mọi đoạn của bảng job không: hoặc nối dài nguyên byte, hoặc toàn bộ dòng hợp lệ
    (bảng job có thể bị _resume viết lại / cụt dòng cuối) — và bản staged phải sạch (không dòng rác), có ít nhất một dòng."""
    try:
        if staged.read_bytes().startswith(current.read_bytes()):
            return True
    except OSError:
        return False
    kept, wanted = _table_lines(staged), _table_lines(current)
    if not kept or wanted is None:
        return False
    try:
        total = sum(1 for line in staged.read_text(encoding="utf-8").splitlines() if line.strip())
    except (OSError, ValueError):
        return False
    return len(kept) == total and set(wanted) <= set(kept)


def _restore_tables(directory: Path, staging: Path) -> None:
    """Đưa bảng đoạn từ rebuild/ về thư mục job — chỉ khi nó giữ được mọi đoạn của bảng hiện có (xem `_extends`);
    bảng hỏng/ngắn hơn thì giữ bản của job. meta đi cùng bảng được giữ."""
    table = TABLE_FILES[0]
    if not (staging / table).is_file():
        return
    if (directory / table).is_file() and not _extends(directory / table, staging / table):
        return
    for name in TABLE_FILES:
        if (staging / name).is_file():
            os.replace(staging / name, directory / name)


def _replace_tables(directory: Path, staging: Path) -> None:
    """Dịch lại từ đầu xong: bảng cũ thuộc lựa chọn cũ — bỏ; bảng mới trong rebuild/ (nếu worker có ghi) thay vào, KHÔNG qua
    phép kiểm "nối dài" của _restore_tables (giữ bảng cũ là sai meta)."""
    for name in TABLE_FILES:
        (directory / name).unlink(missing_ok=True)
        if (staging / name).is_file():
            os.replace(staging / name, directory / name)


def _copy_tables(src: Path, dst: Path) -> None:
    """Chép các tệp TABLE_FILES có trong `src` sang `dst`. CHÉP, không chuyển: `src` giữ nguyên; tệp cùng tên ở `dst` bị ghi đè;
    tệp không có ở `src` thì `dst` không đổi. KHÔNG nguyên tử: lỗi giữa chừng (ENOSPC) có thể để lại một phần ở `dst` rồi ném
    ngoại lệ — người gọi lo dọn `dst`."""
    for name in TABLE_FILES:
        if (src / name).is_file():
            shutil.copyfile(src / name, dst / name)


def _rescue_backup(directory: Path, staging: Path, output_name: str | None) -> None:
    """Bản dịch cũ còn nằm trong rebuild/.previous mà thư mục job không có tệp đó (chết / lỗi giữa lúc thay) → trả lại."""
    backup = staging / BACKUP_NAME
    if output_name and backup.is_file() and not (directory / output_name).exists():
        os.replace(backup, directory / output_name)


def _rescue_orphan_versions(directory: Path, output_name: str | None, known: frozenset[str]) -> None:
    """versions/<x>/ KHÔNG có dòng file_versions = thao tác bị ngắt (spec 2026-10-14 §5): (a) chết giữa "cất bản cũ vào kho" và
    commit → bản cũ chỉ còn ở đó, thư mục job thiếu output_name → trả về; (b) tỉa đã commit, rmtree chưa kịp → rác → xoá.
    Thư mục có dòng (`known`) không đụng. Chỉ runner gọi (giữ khoá, job đang được nhận)."""
    store = directory / VERSIONS_DIR
    if not store.is_dir():
        return
    for child in store.iterdir():
        if child.name in known or not child.is_dir() or child.is_symlink():
            continue
        if output_name and not (directory / output_name).exists() and (child / output_name).is_file():
            os.replace(child / output_name, directory / output_name)
        shutil.rmtree(child, ignore_errors=True)


def _rescue_interrupted_swap(directory: Path, output_name: str | None, known_versions: frozenset[str]) -> None:
    """Trả bản dịch hiện tại về thư mục job sau một lượt thay bị ngắt. THỨ TỰ có nghĩa: rebuild/.previous trước (chết giữa bước
    1–2 của spec 2026-10-14 §5: nó CHÍNH LÀ bản hiện tại), rồi mới tới versions/<x>/ mồ côi (chết giữa bước 3–4 — lúc đó .previous
    đã không còn). Làm ngược lại thì một thư mục mồ côi cũ (tỉa xong chưa kịp xoá) trùng tên chiếm chỗ, và .previous bị xoá theo
    rebuild/. Gọi từ _execute (trước các lối thoát sớm) và _staging — cùng một hàm để không bao giờ lệch thứ tự."""
    _rescue_backup(directory, directory / REBUILD_DIR, output_name)
    _rescue_orphan_versions(directory, output_name, known_versions)


def _tail(path: Path, lines: int = 3) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return " / ".join(text.splitlines()[-lines:])


class JobRunner:
    def __init__(
        self,
        session_factory: sessionmaker,
        users_dir: Path,
        worker_cmd: Sequence[str],
        *,
        lock_path: Path,
        handoff_worker_cmd: Sequence[str] = (),
        secret_key: str = "",
        max_concurrent: int = 1,
        stall_seconds: float = 480,
        timeout_seconds: float = 10800,
        poll_seconds: float = 1.0,
        lock_retry_seconds: float = 3.0,
    ) -> None:
        self._sessions = session_factory
        self._users_dir = users_dir
        self._worker_cmd = tuple(worker_cmd)
        self._lock_path = lock_path
        self._handoff_cmd = tuple(handoff_worker_cmd)
        self._secret_key = secret_key
        self._max_concurrent = max_concurrent
        self._stall = stall_seconds
        self._timeout = timeout_seconds
        self._poll = poll_seconds
        self._lock_retry = lock_retry_seconds
        self._progress: dict[str, Progress] = {}
        self._processes: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._started = False
        self._lock_fd: int | None = None
        self._threads: list[threading.Thread] = []

    @classmethod
    def from_settings(cls, settings: Settings, session_factory: sessionmaker) -> JobRunner:
        return cls(
            session_factory, settings.users_dir, settings.worker_cmd,
            lock_path=settings.data_dir / "runner.lock",
            handoff_worker_cmd=settings.handoff_worker_cmd, secret_key=settings.secret_key,
            max_concurrent=settings.max_concurrent_jobs,
            stall_seconds=settings.job_stall_seconds,
            timeout_seconds=settings.job_timeout_seconds,
        )

    # ---- API cho tầng web -------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        if not self._take_lock():
            log.warning("Runner khác đang giữ %s — tiến trình này chỉ phục vụ web, thử lại mỗi %ss",
                        self._lock_path, self._lock_retry)
            waiter = threading.Thread(target=self._wait_for_lock, name="job-runner-lock", daemon=True)
            waiter.start()
            with self._lock:
                self._threads.append(waiter)

    def stop(self) -> None:
        """Dừng khi tắt máy: giết worker nhưng KHÔNG đánh dấu lỗi — runner giữ khoá kế tiếp chạy lại."""
        self._stopping.set()
        self._wake.set()
        with self._lock:
            processes = list(self._processes)
            threads, self._threads = self._threads, []
        for process in processes:
            process.kill()
        current = threading.current_thread()
        for thread in threads:
            if thread is not current:
                thread.join(STOP_JOIN_SECONDS)
        # Thả khoá SAU khi các luồng đã thoát: runner kế tiếp không phục hồi một job còn đang được ghi.
        with self._lock:
            fd, self._lock_fd = self._lock_fd, None
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def enqueue(self, file_id: str) -> None:
        """Dòng đã nằm trong DB — chỉ đánh thức luồng chạy cho khỏi đợi tới lượt quét kế."""
        self._wake.set()

    def progress(self, file_id: str) -> Progress | None:
        with self._lock:
            current = self._progress.get(file_id)
            return None if current is None else Progress(
                current.done, current.total, current.written_pct, current.stage, current.engine_label
            )

    def queue_depth(self) -> int:
        with self._sessions() as db:
            return db.scalar(select(func.count()).select_from(File).where(File.status == "queued")) or 0

    # ---- Khoá: một runner cho mỗi thư mục dữ liệu ------------------------------

    def _take_lock(self) -> bool:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        with self._lock:
            if self._stopping.is_set():
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                return False
            self._lock_fd = fd
        # Chỉ người vừa giữ khoá mới được phục hồi: job "running" lúc này chắc chắn không còn ai chạy.
        try:
            self._recover()
        except Exception:
            # Thả khoá: giữ lại thì lần thử sau (fd mới) bị chính khoá của mình chặn mãi mãi.
            with self._lock:
                if self._lock_fd == fd:
                    self._lock_fd = None
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
            raise
        workers = [
            threading.Thread(target=self._work, name=f"job-runner-{index}", daemon=True)
            for index in range(self._max_concurrent)
        ]
        with self._lock:
            if self._stopping.is_set():
                return True  # stop() đang chạy: nó sẽ thả khoá
            self._threads.extend(workers)
            for worker in workers:
                worker.start()
        return True

    def _wait_for_lock(self) -> None:
        while not self._stopping.wait(self._lock_retry):
            try:
                if self._take_lock():
                    log.warning("Đã giữ %s — bắt đầu chạy hàng đợi", self._lock_path)
                    return
            except Exception:  # noqa: BLE001 - luồng chờ khoá không được chết vì một lỗi DB/đĩa
                log.exception("Lấy khoá runner thất bại, sẽ thử lại")

    # ---- Vòng chạy nền ----------------------------------------------------

    def _recover(self) -> None:
        # rebuild_font + retranslate_* giữ nguyên: job "dựng lại" / "dịch lại" bị ngắt (restart) được chạy lại như cũ.
        with self._sessions() as db:
            db.execute(update(File).where(File.status == "running").values(
                status="queued", done_pages=0, total_pages=0, message="", started_at=None, finished_at=None,
                stage="",
            ))
            db.commit()

    def _claim_next(self) -> str | None:
        """Nhận dòng queued cũ nhất. Nhận có điều kiện: luồng/tiến trình khác giành trước thì thử dòng kế."""
        with self._sessions() as db:
            while True:
                file_id = db.scalar(
                    select(File.id).where(File.status == "queued").order_by(File.created_at, File.id).limit(1)
                )
                if file_id is None:
                    return None
                claimed = db.execute(
                    update(File)
                    .where(File.id == file_id, File.status == "queued")
                    .values(status="running", started_at=utcnow(), finished_at=None,
                            message="Đang phân tích bố cục trang…")
                ).rowcount
                db.commit()
                if claimed:
                    return file_id

    def _work(self) -> None:
        while not self._stopping.is_set():
            # Xoá cờ TRƯỚC khi quét: enqueue() đến sau lượt quét vẫn đánh thức được lần chờ dưới.
            self._wake.clear()
            try:
                file_id = self._claim_next()
            except Exception:  # noqa: BLE001 - DB trục trặc: đợi rồi quét lại, đừng chết luồng
                log.exception("Không nhận được việc từ DB")
                file_id = None
            if file_id is None:
                self._wake.wait(self._poll)
                continue
            try:
                self._execute(file_id)
            except Exception as error:  # noqa: BLE001 - luồng phải sống để hàng đợi không tắc
                log.exception("Job %s hỏng", file_id)
                if not self._stopping.is_set():
                    try:
                        # Người dùng chỉ thấy tên lớp lỗi: chuỗi lỗi có thể chứa đường dẫn máy chủ / errno,
                        # bản đầy đủ đã nằm trong log ngay trên.
                        self._finish(file_id, status="error", message=f"Lỗi nội bộ ({type(error).__name__}).")
                    except Exception:  # noqa: BLE001 - lỗi khi ghi lỗi cũng không được giết luồng
                        log.exception("Job %s: không ghi được trạng thái lỗi", file_id)

    def _execute(self, file_id: str) -> None:
        """Chạy một job ĐÃ nhận (status = running). Engine cần key: giải mã key của chủ tệp NGAY LÚC NÀY —
        xoá key / đổi SECRET_KEY trước khi tới lượt là job lỗi với hướng dẫn, không chạy worker."""
        with self._sessions() as db:
            row = db.get(File, file_id)
            if row is None or row.status != "running":
                return
            user_id = row.user_id
            directory = file_dir(self._users_dir, row.user_id, row.id)
            source = directory / safe_name(row.filename)
            retranslating = row.retranslate_language is not None
            if retranslating:
                # Dịch lại từ đầu (spec 2026-10-05 §6): lựa chọn MỚI ở retranslate_*; language/engine/model giữ bản cũ tới khi xong.
                language, engine_id, model = row.retranslate_language, row.retranslate_engine or "", row.retranslate_model or ""
            else:
                language, engine_id, model = row.language, row.engine, row.model or ""
            # Chỉ dẫn văn phong của LƯỢT này (spec 2026-10-14 §4): dịch lại → snapshot đang đỗ; dựng lại font / dịch lần đầu → snapshot hiện tại.
            config_text = row.retranslate_config if retranslating else row.config
            # Dựng lại font HOẶC dịch lại: chạy trong rebuild/, bản cũ còn nguyên tới khi thay. Dịch lại luôn có rebuild_font
            # (service ghi cùng một UPDATE) — vẫn xét cả retranslate_*: thiếu rebuild_font thì font lùi về font của tệp.
            staged = row.rebuild_font is not None or retranslating
            previous_output = row.output_name
            font = row.rebuild_font or row.font
            # Id các bản cũ có dòng DB: thư mục versions/<x>/ ngoài danh sách là thao tác bị ngắt (_rescue_orphan_versions).
            known_versions = (frozenset(db.scalars(select(FileVersion.id).where(FileVersion.file_id == row.id)).all())
                              if staged else frozenset())
            # Khôi phục bản cũ (spec 2026-10-15 §2): restore_version đi cùng retranslate_* + rebuild_font của bản nguồn (service ghi một
            # UPDATE) nên `retranslating`/`staged` ở trên đã đúng; đọc dòng nguồn NGAY — không còn dòng thì coi như tệp nguồn mất.
            restoring = row.restore_version is not None
            source_version = db.get(FileVersion, row.restore_version) if restoring else None
            restore_source = (RestoreSource(store=directory / VERSIONS_DIR / source_version.id, output_name=source_version.output_name,
                                            untranslated=source_version.untranslated, font_used=source_version.font_used)
                              if source_version is not None else None)
            engine = ENGINE_BY_ID.get(engine_id)
            api_key = None
            if engine is not None and engine.provider is not None and not restoring:  # khôi phục không cần key
                api_key = load_api_key(db, self._secret_key, row.user_id, engine.provider)
        if staged:
            # Lượt thay trước bị ngắt → bản hiện tại có thể chỉ còn trong rebuild/.previous hoặc versions/<x>/ mồ côi. Cứu NGAY,
            # trước mọi lối thoát sớm dưới đây (engine lạ, thiếu key, thiếu worker handoff): các lối đó đi _abort — vốn không đụng
            # versions/ — và tệp trở lại `done` mà tải xuống 410. _staging gọi lại (không còn gì để làm).
            _rescue_interrupted_swap(directory, previous_output, known_versions)
        if restoring:
            # Không worker, không key, không API: rẽ TRƯỚC kiểm engine/key/worker — người đã xoá key Gemini vẫn khôi phục được bản
            # Gemini cũ. Outcome đi vào _finish → nhánh staged → _finish_rebuild y như một lượt dịch lại vừa xong.
            self._finish(file_id, **self._stage_restore(directory, previous_output, known_versions, restore_source))
            return
        if engine is None:
            self._finish(file_id, status="error", message=f"Engine dịch không được hỗ trợ: {engine_id}")
            return
        # Bản sao env của tiến trình web, bỏ biến nhạy cảm — cho CẢ HAI worker (font_worker cần TRANSLATE_FONT).
        env = {name: value for name, value in os.environ.items() if name not in SENSITIVE_ENV_KEYS}
        env["TRANSLATE_FONT"] = font
        cmd = self._worker_cmd
        if engine.provider is not None:
            if api_key is None:
                self._finish(file_id, status="error",
                             message=MISSING_KEY_MESSAGE.format(provider=PROVIDER_LABELS[engine.provider]))
                return
            if not self._handoff_cmd:
                # Thiếu cấu hình: không bao giờ được lùi về worker thường (nó không biết dịch qua
                # provider) — lỗi rõ ràng còn hơn âm thầm chạy sai.
                self._finish(file_id, status="error", message=NO_HANDOFF_WORKER_MESSAGE)
                return
            cmd = self._handoff_cmd
            # Key đi qua env, KHÔNG qua argv: `ps` của mọi user trên máy đọc được argv.
            # Chỉ worker handoff nhận chỉ dẫn (động cơ thuần không có prompt); chuỗi là nội dung người dùng → đi qua env như key, không argv.
            env.update(TRANSLATE_PROVIDER=engine.provider, TRANSLATE_API_KEY=api_key, TRANSLATE_MODEL=model,
                       TRANSLATE_INSTRUCTIONS=build_instructions(load_snapshot(config_text), language))
        output_dir = (self._staging(directory, previous_output, keep_job_tables=not retranslating, known_versions=known_versions)
                      if staged else directory)
        with self._lock:
            self._progress[file_id] = Progress(engine_label=engine.label)
        try:
            outcome = self._run_worker(file_id, source, output_dir, language, cmd, env, api_key)
        finally:
            with self._lock:
                self._progress.pop(file_id, None)
        if not self._stopping.is_set():
            # Model bị Google gỡ (§3): gỡ khỏi danh sách của key để ô chọn không còn đưa ra nữa.
            if outcome.pop("code", "") == "model_unavailable" and engine.id == "gemini" and model:
                outcome["message"] += self._drop_model(user_id, model)
            self._finish(file_id, **outcome)

    def _drop_model(self, user_id: str, model: str) -> str:
        """Trả câu nối vào thông điệp lỗi khi model mặc định vừa bị đổi, "" nếu không."""
        try:
            with self._sessions() as db:
                label = drop_gemini_model(db, user_id, model)
        except Exception:  # noqa: BLE001 - gỡ model hỏng không được làm mất thông điệp lỗi gốc của job
            log.exception("Không gỡ được model %s khỏi danh sách của key", model)
            return ""
        return "" if label is None else MODEL_DROPPED_NOTE.format(label=label)

    def _stage_restore(self, directory: Path, previous_output: str | None, known_versions: frozenset[str],
                       source: RestoreSource | None) -> dict:
        """Chép bản nguồn (PDF + bảng đoạn nếu có) vào rebuild/ làm "đầu ra mới" của lượt này rồi trả outcome cho _finish (spec
        2026-10-15 §2). _staging(keep_job_tables=False) cố ý giữ segments.* của một lượt dịch lại bị ngắt — chúng KHÔNG phải của bản
        nguồn nên xoá trước. PDF chép sang .tmp rồi os.replace: chết giữa chừng không để lại tệp cụt mang tên kết quả (lần chạy lại
        _staging dọn .tmp). Bản nguồn mất (dòng / tệp) → outcome lỗi → _abort: tệp về `done` với rebuild_error, kho nguyên."""
        staging = self._staging(directory, previous_output, keep_job_tables=False, known_versions=known_versions)
        for name in TABLE_FILES:
            (staging / name).unlink(missing_ok=True)
        if source is None or not (source.store / source.output_name).is_file():
            return {"status": "error", "message": RESTORE_SOURCE_MISSING_MESSAGE}
        temp = staging / (source.output_name + ".tmp")
        shutil.copyfile(source.store / source.output_name, temp)
        os.replace(temp, staging / source.output_name)
        _copy_tables(source.store, staging)  # bảng của bản nguồn (nếu có) — _replace_tables đưa vào thư mục job sau commit
        return {"status": "done", "message": "Xong", "output_name": source.output_name, "untranslated": source.untranslated,
                "font_used": source.font_used}

    @staticmethod
    def _staging(directory: Path, output_name: str | None = None, *, keep_job_tables: bool = True,
                 known_versions: frozenset[str] = frozenset()) -> Path:
        """Thư mục rebuild/ cho một lượt thay bản dịch.
        keep_job_tables=True (dựng lại font): bảng dở của lượt trước (nếu dài hơn) trả về thư mục job, rồi chép bảng job vào
        staging → worker handoff dùng lại (0 lời gọi API).
        keep_job_tables=False (dịch lại từ đầu): KHÔNG chép bảng job (thuộc lựa chọn cũ) và KHÔNG trả bảng dở về job (thuộc
        lựa chọn mới); giữ nguyên segments.* trong rebuild/ (đoạn đã trả tiền của lượt dịch lại bị ngắt), dọn mọi thứ khác.
        `known_versions` = id file_versions của tệp — thư mục versions/<x>/ ngoài danh sách là mồ côi: có tệp đúng tên mà thư mục
        job thiếu thì trả về, không thì xoá (_rescue_interrupted_swap)."""
        staging = directory / REBUILD_DIR
        _rescue_interrupted_swap(directory, output_name, known_versions)  # .previous rồi kho mồ côi — chết giữa lúc thay / cất / tỉa
        if keep_job_tables:
            _restore_tables(directory, staging)  # đoạn đã trả tiền của lượt dựng lại bị ngắt không được mất theo
            shutil.rmtree(staging, ignore_errors=True)  # lượt dựng lại dở của lần chạy trước (restart giữa chừng)
            staging.mkdir()
            _copy_tables(directory, staging)
            return staging
        staging.mkdir(exist_ok=True)
        for child in staging.iterdir():
            if child.name in TABLE_FILES:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        return staging

    def _run_worker(
        self, file_id: str, source: Path, directory: Path, language: str,
        cmd: Sequence[str] | None = None, env: dict | None = None, api_key: str | None = None,
    ) -> dict:
        error_log = directory / ERROR_LOG_NAME
        started = time.monotonic()
        last_progress = started
        done = total = 0
        stage = ""  # bước của dòng tiến độ cuối — thông điệp "đứng" tính theo trang hay theo đoạn
        font_used: str | None = None  # dòng {"font"} của worker; ghi vào files.font_used khi job xong
        result: dict | None = None
        stalled, expired, finished = threading.Event(), threading.Event(), threading.Event()

        # stderr đi thẳng ra TỆP, tuyệt đối không dùng ống: ống đầy (64KB) làm tiến trình
        # con chặn lúc ghi trong khi cha chặn lúc đọc stdout — bế tắc (BUG-0001 của vi-translate).
        with error_log.open("w", encoding="utf-8", errors="replace") as errors, subprocess.Popen(
            [*(cmd or self._worker_cmd), str(source), str(directory), language],
            stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", env=env,
        ) as process:
            with self._lock:
                self._processes.add(process)

            def watch() -> None:
                interval = max(0.2, min(15.0, min(self._stall, self._timeout) / 4))
                while not finished.wait(interval):
                    now = time.monotonic()
                    if now - last_progress > self._stall:
                        stalled.set()
                    elif now - started > self._timeout:
                        expired.set()
                    else:
                        continue
                    process.kill()
                    return

            threading.Thread(target=watch, daemon=True).start()
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # nhân upstream cũng in log thường ra stdout
                    if not isinstance(payload, dict):
                        continue
                    if "p" in payload:
                        try:
                            done, total = int(payload.get("p", 0)), int(payload.get("t", 0))
                        except (TypeError, ValueError):
                            continue  # dòng tiến độ hỏng kiểu — bỏ qua, đừng để cả job chết theo
                        stage = str(payload.get("stage") or "")[:12]
                        last_progress = time.monotonic()  # mọi bước đều làm mới đồng hồ stall
                        self._report_progress(file_id, done, total, stage)
                    elif "ok" in payload:
                        result = payload
                    elif "font" in payload:
                        value = payload["font"]  # dòng hỏng kiểu (không phải chuỗi hồ sơ) bị bỏ qua như dòng tiến độ hỏng
                        font_used = value if isinstance(value, str) and value in FONT_PROFILES else None
                code = process.wait()
            finally:
                # Bất kể vòng đọc ở trên thoát ra sao (EOF bình thường hay một ngoại lệ bất kỳ,
                # vd lỗi DB trong _report_progress) — tiến trình con không được sống sót ra khỏi
                # hàm này. Sống sót nghĩa là stop() không giết được nó và job sau chạy chồng lên
                # nó, phá vỡ max_concurrent.
                finished.set()
                if process.poll() is None:
                    process.kill()
                    process.wait()
                with self._lock:
                    self._processes.discard(process)

        pages = {"done_pages": done, "total_pages": total}
        if stalled.is_set():
            where = f"{done}/{total}" if total else "?"
            unit = "đoạn" if stage == "translate" else "trang"  # bước dịch đếm đoạn văn, các bước khác đếm trang
            outcome = {"status": "error", **pages, "message": (
                f"Dừng vì không nhích thêm {unit} nào suốt {_minutes(self._stall)} phút (đứng ở {unit} {where}). "
                "Hai nguyên nhân thường gặp: máy chủ mất đường ra Internet, hoặc dịch vụ dịch đang chặn tốc độ "
                "vì tài liệu quá dài. Với tài liệu dài, hãy chia nhỏ rồi dịch từng phần."
            )}
        elif expired.is_set():
            outcome = {"status": "error", **pages, "message": (
                f"Quá {_minutes(self._timeout)} phút vẫn chưa xong nên đã dừng. Tài liệu này quá dài so với hạn mức."
            )}
        elif result is None:
            detail = _tail(error_log) or f"mã thoát {code}"
            outcome = {"status": "error", **pages, "message": f"Tiến trình dịch dừng đột ngột ({detail})"}
        elif not result.get("ok"):
            outcome = {"status": "error", **pages, "message": str(result.get("error") or "Dịch thất bại"),
                       "code": str(result.get("code") or "")}
        else:
            output = Path(str(result.get("output", "")))
            if (
                output.parent.resolve() != directory.resolve()
                or output.resolve() == source.resolve()
                or output.name in {source.name, ERROR_LOG_NAME, BACKUP_NAME, *TABLE_FILES}  # dựng lại: rebuild/<tên nguồn> không
                # trùng đường dẫn nguồn nhưng os.replace sẽ đè bản tải lên; tên bảng/log của chính runner cũng cấm
                or not output.is_file()
            ):
                outcome = {"status": "error", **pages,
                           "message": "Nhân dịch báo xong nhưng không tìm thấy tệp kết quả."}
            else:
                outcome = {"status": "done", **pages, "message": "Xong", "output_name": output.name,
                           "untranslated": int(result.get("untranslated", 0)), "font_used": font_used}
        if api_key:
            # Văn bản worker tự in ra (đuôi stderr, "error" của JSON) có thể vô tình chứa key —
            # che trước khi lưu, dù key đi qua env chứ không qua đây.
            outcome["message"] = outcome["message"].replace(api_key, "***")
        return outcome

    def _report_progress(self, file_id: str, done: int, total: int, stage: str = "") -> None:
        if stage not in KNOWN_STAGES:
            stage = ""  # worker hỏng/giả gửi stage lạ: không lưu nguyên văn, cũng không hiện ra UI
        pct = _pct(done, total)
        with self._lock:
            progress = self._progress.setdefault(file_id, Progress())
            if stage != progress.stage:
                progress.stage, progress.written_pct = stage, -100  # bước mới: ghi DB ngay dòng đầu
            progress.done, progress.total = done, total
            write = pct - progress.written_pct >= PROGRESS_WRITE_STEP or (total > 0 and done == total)
            if write:
                progress.written_pct = pct
            message = STAGE_MESSAGES.get(stage, STAGE_MESSAGES[""]).format(engine=progress.engine_label)
        if write:
            with self._sessions() as db:
                db.execute(update(File).where(File.id == file_id, File.status == "running").values(
                    done_pages=done, total_pages=total, message=message, stage=stage,
                ))
                db.commit()

    def _finish(
        self, file_id: str, *, status: str, message: str, output_name: str | None = None,
        untranslated: int = 0, done_pages: int | None = None, total_pages: int | None = None,
        font_used: str | None = None,
    ) -> None:
        with self._sessions() as db:
            row = db.get(File, file_id)
            # Chỉ dòng còn "running": dòng đã bị phục hồi về queued (runner khác tiếp quản) / đã xoá thì để yên.
            if row is None or row.status != "running":
                return
            user_id, previous_output = row.user_id, row.output_name
            retranslate = ((row.retranslate_language, row.retranslate_engine or "", row.retranslate_model or "",
                            row.retranslate_config) if row.retranslate_language is not None else None)
            staged = row.rebuild_font is not None or retranslate is not None  # cùng điều kiện với _execute
            new_font = row.rebuild_font or row.font
            # Bản ĐANG là bản chính + hạn giữ: đọc TRƯỚC khi _finish_rebuild ghi đè dòng (spec 2026-10-14 §5).
            previous = Previous(output_name=row.output_name, language=row.language, engine=row.engine, model=row.model, font=row.font,
                                font_used=row.font_used, untranslated=row.untranslated, finished_at=row.finished_at,
                                config=row.config, version_no=row.version_no, translated_at=row.translated_at,
                                restored_from=row.restored_from)
            max_versions = effective_max_versions(db) if retranslate is not None and status == "done" else 1
            # Khôi phục: số của bản nguồn ghi vào files.restored_from cùng giao dịch (spec 2026-10-15 §2); dịch lại thường → None.
            restored_from = (db.scalar(select(FileVersion.version_no).where(FileVersion.id == row.restore_version))
                             if row.restore_version is not None else None)
        pages = {key: value for key, value in (("done_pages", done_pages), ("total_pages", total_pages))
                 if value is not None}
        if staged:
            if status == "done":
                self._finish_rebuild(file_id, user_id, new_font, previous_output, retranslate=retranslate, message=message,
                                     output_name=output_name, untranslated=untranslated, font_used=font_used,
                                     previous=previous, max_versions=max_versions, restored_from=restored_from, **pages)
            else:
                self._abort(file_id, user_id, message, previous_output, retranslating=retranslate is not None)
            return
        values: dict = {"status": status, "message": message[:MESSAGE_LIMIT], "output_name": output_name,
                        "untranslated": untranslated, "finished_at": utcnow(), "stage": "", **pages}
        if status == "done":
            values["font_used"] = font_used
            values["translated_at"] = values["finished_at"]  # bản dịch vừa hoàn tất (spec 2026-10-15 §4)
        self._update_running(file_id, values)

    def _finish_rebuild(
        self, file_id: str, user_id: str, rebuild_font: str, previous_output: str | None, *,
        retranslate: tuple[str, str, str, str | None] | None, message: str,
        output_name: str | None, untranslated: int, font_used: str | None,
        previous: Previous | None = None, max_versions: int = 1, restored_from: int | None = None, **pages: int,
    ) -> None:
        """Dựng lại / dịch lại xong: bản dịch mới (và bảng đoạn — có thể vừa được bổ sung) thay bản cũ trên đĩa, rồi mới ghi DB.
        `rebuild_font` = font của bản mới. Dịch lại (`retranslate` = (language, engine, model, config) từ retranslate_*, BẮT
        BUỘC truyền tên — None là dựng lại font): language/engine/model lấy từ đó, bảng mới thay hẳn bảng cũ; phần tử thứ tư =
        snapshot của lượt dịch lại (`retranslate_config`), đổi chỗ vào `config` khi xong. Thứ tự (spec 2026-10-14 §5):
        (1) bản cũ → rebuild/.previous; (2) bản mới vào thư mục job; (3) chỉ khi dịch lại, có bản cũ, `max_versions` > 1:
        .previous → versions/<vid>/<tên cũ> (`previous` = metadata của nó, đọc trong _finish) + chép bảng đoạn của thư mục job vào
        đó (_copy_tables); (4) INSERT file_versions + tỉa + UPDATE files là MỘT giao dịch (_commit_swap); (5) lỗi / dòng không còn
        running → _put_back trả cả tệp đã cất (kèm rmtree versions/<vid>/ — bản sao bảng đi theo);
        (6) sau commit: xoá thư mục đã tỉa, thay bảng, xoá rebuild/. Dựng lại font ghi DB qua _update_running như cũ.
        restored_from = số của bản nguồn khi lượt này là khôi phục (_finish đọc theo restore_version), None với dịch lại thường —
        ghi vào files.restored_from cùng giao dịch, kèm restore_version về NULL."""
        directory = file_dir(self._users_dir, user_id, file_id)
        staging = directory / REBUILD_DIR
        backup = staging / BACKUP_NAME  # bản cũ cất tạm: DB ghi hỏng thì trả lại đúng tên, tên mới trùng tên cũ cũng vậy
        moved_in = False
        archived: Path | None = None  # versions/<vid>/<tên cũ> — đặt ngay sau mkdir: chuyển hỏng thì _put_back vẫn dọn thư mục
        version_id = uuid.uuid4().hex[:12]
        try:
            if previous_output and (directory / previous_output).is_file():
                os.replace(directory / previous_output, backup)
            if output_name and (staging / output_name).is_file():
                os.replace(staging / output_name, directory / output_name)
                moved_in = True
            if retranslate is not None and previous is not None and previous_output and max_versions > 1 and backup.is_file():
                store = directory / VERSIONS_DIR / version_id
                store.mkdir(parents=True)
                archived = store / previous_output
                os.replace(backup, archived)  # cùng hệ tệp: đổi tên, không chép, không tốn thêm đĩa
                # Bảng đoạn của bản cũ đi theo bản cũ (spec 2026-10-15 §3) — CHÉP: bảng ở thư mục job lúc này vẫn là của bản cũ
                # (dịch lại / khôi phục không chép bảng job vào rebuild/, xem _staging) và thư mục job phải nguyên tới khi
                # _replace_tables thay SAU commit. Commit hỏng → _put_back rmtree cả versions/<vid>/ nên bản sao đi theo; chép
                # hỏng (ENOSPC) → ngoại lệ → _put_back như lỗi DB. Khôi phục bản này sau này mang bảng về → dựng lại font 0 lời gọi API.
                _copy_tables(directory, store)
            now = utcnow()
            values = {
                "status": "done", "message": message[:MESSAGE_LIMIT], "output_name": output_name,
                "untranslated": untranslated, "finished_at": now, "stage": "",
                "font": rebuild_font, "font_used": font_used, "rebuild_font": None, **pages,
            }
            if retranslate is not None:
                language, engine_id, model, config = retranslate
                values.update(language=language, engine=engine_id, model=model or None, config=config,
                              retranslate_language=None, retranslate_engine=None, retranslate_model=None, retranslate_config=None,
                              version_no=File.version_no + 1, translated_at=now, restored_from=restored_from, restore_version=None)
                updated, pruned = self._commit_swap(file_id, values, previous if archived is not None else None, version_id,
                                                    keep=max(0, max_versions - 1))
            else:
                updated, pruned = self._update_running(file_id, values), []
        except Exception:
            self._put_back(directory, output_name, previous_output, backup, moved_in, archived)
            raise
        if not updated:  # dòng không còn running (runner khác đã phục hồi): không đổi gì trên đĩa
            self._put_back(directory, output_name, previous_output, backup, moved_in, archived)
            return
        for pruned_id in pruned:  # sau commit: thư mục của dòng đã tỉa (chết trước bước này → mồ côi, _staging lần sau dọn)
            shutil.rmtree(directory / VERSIONS_DIR / pruned_id, ignore_errors=True)
        if retranslate is not None:
            _replace_tables(directory, staging)  # bảng của lựa chọn mới thay hẳn bảng cũ
        else:
            _restore_tables(directory, staging)
        shutil.rmtree(staging, ignore_errors=True)  # kéo theo .previous (khi không cất) — chỉ xoá sau khi DB đã trỏ sang bản mới

    def _commit_swap(self, file_id: str, values: dict, archive: Previous | None, version_id: str, *,
                     keep: int) -> tuple[bool, list[str]]:
        """MỘT giao dịch cho lượt dịch lại: UPDATE files có điều kiện (còn running), chèn dòng file_versions (khi bản cũ đã được
        cất — `archive`), chọn + xoá các dòng vượt `keep` bản cũ (= max_versions - 1; tỉa ở MỌI lần dịch lại thành công, kể cả
        không cất — hạ hạn về 1 vẫn dọn kho). UPDATE đi trước: rowcount 0 → rollback, không chèn dòng nào (khỏi vấp khoá ngoại
        khi dòng đã bị xoá). Trả (đã ghi?, id các dòng đã tỉa)."""
        with self._sessions() as db:
            if not db.execute(update(File).where(File.id == file_id, File.status == "running").values(**values)).rowcount:
                db.rollback()
                return False, []
            if archive is not None:
                db.add(FileVersion(id=version_id, file_id=file_id, version_no=archive.version_no, language=archive.language,
                                   engine=archive.engine, model=archive.model, font=archive.font, font_used=archive.font_used,
                                   config=archive.config, output_name=archive.output_name or "", untranslated=archive.untranslated,
                                   finished_at=archive.finished_at, translated_at=archive.translated_at,
                                   restored_from=archive.restored_from, archived_at=utcnow()))
                db.flush()
            pruned = list(db.scalars(
                select(FileVersion.id).where(FileVersion.file_id == file_id)
                .order_by(FileVersion.version_no.desc(), FileVersion.archived_at.desc()).offset(keep)
            ).all())
            if pruned:
                db.execute(delete(FileVersion).where(FileVersion.id.in_(pruned)))
            db.commit()
        return True, pruned

    @staticmethod
    def _put_back(directory: Path, output_name: str | None, previous_output: str | None, backup: Path,
                  moved_in: bool, archived: Path | None = None) -> None:
        """Hoàn tác phần đã làm: chỉ xoá bản mới nếu CHÍNH lần này đã chép vào; bản cũ đã cất vào kho (`archived`) về lại
        .previous rồi xoá thư mục versions/<vid>/ (chỉ sau khi đã lấy tệp ra); chỉ trả bản cũ nếu đã cất. Lỗi ở đây không được
        che lỗi gốc — `_abort` còn cứu `.previous` trước khi xoá rebuild/, _staging lần sau cứu thư mục kho mồ côi."""
        try:
            if moved_in and output_name:
                (directory / output_name).unlink(missing_ok=True)
            if archived is not None:
                if archived.is_file():
                    os.replace(archived, backup)
                shutil.rmtree(archived.parent, ignore_errors=True)
            if previous_output and backup.is_file():
                os.replace(backup, directory / previous_output)
        except Exception:  # noqa: BLE001
            log.exception("Không hoàn tác được việc thay bản dịch của %s", directory.name)

    def _abort(self, file_id: str, user_id: str, reason: str, previous_output: str | None = None, *,
               retranslating: bool = False) -> None:
        """Dựng lại thất bại — MỌI nguyên nhân (worker lỗi, đứng, quá giờ, lỗi nội bộ, thiếu key…): bản dịch cũ còn
        nguyên ở thư mục job; tệp trở lại `done` với font/untranslated cũ, lý do vào `rebuild_error`. Dịch lại thất bại
        cũng vậy: retranslate_* về NULL, bảng cũ nguyên (không trả bảng của lựa chọn mới về job). Khôi phục thất bại (bản nguồn
        mất, lỗi nội bộ) cũng vậy: restore_version về NULL."""
        directory = file_dir(self._users_dir, user_id, file_id)
        staging = directory / REBUILD_DIR
        _rescue_backup(directory, staging, previous_output)  # trước khi rmtree: đừng xoá bản cũ duy nhất
        if (staging / ERROR_LOG_NAME).is_file():
            os.replace(staging / ERROR_LOG_NAME, directory / "rebuild-stderr.log")  # để chẩn đoán
        if not retranslating:
            _restore_tables(directory, staging)  # dựng lại: bảng trong rebuild/ có thể đầy hơn — đừng mất đoạn đã trả tiền
        shutil.rmtree(staging, ignore_errors=True)
        self._update_running(file_id, {
            "status": "done", "message": "Xong", "rebuild_font": None, "rebuild_error": reason[:MESSAGE_LIMIT],
            "retranslate_language": None, "retranslate_engine": None, "retranslate_model": None, "retranslate_config": None,
            "restore_version": None, "finished_at": utcnow(), "stage": "",
        })

    def _update_running(self, file_id: str, values: dict) -> bool:
        """True nếu đã ghi (dòng còn running)."""
        with self._sessions() as db:
            # Có điều kiện: giữa lúc đọc và lúc ghi, runner khác có thể đã phục hồi dòng về queued.
            rowcount = db.execute(
                update(File).where(File.id == file_id, File.status == "running").values(**values)
            ).rowcount
            db.commit()
        return bool(rowcount)
