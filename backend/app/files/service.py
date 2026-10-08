"""Nghiệp vụ tệp — mọi thao tác đều trong phạm vi một user."""

from __future__ import annotations

import errno
import shutil
import unicodedata
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import iso
from ..engine.fonts import PROFILE_IDS
from ..engine.jobs import JobRunner, Progress
from ..engine.paths import file_dir, safe_name
from ..errors import ApiError
from ..models import File, User
from ..providers.credentials import resolve_upload_choice
from ..system.store import effective_pending_limit
from .languages import VALID_LANGUAGES

PENDING = ("queued", "running")
NAME_LIMIT = 200


def normalize_search(text: str) -> str:
    # NFC: tên từ macOS là NFD; casefold: "BÁO" khớp "báo" — LIKE của SQLite chỉ bỏ hoa/thường cho ASCII.
    return unicodedata.normalize("NFC", text).casefold()


def clean_filename(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw).replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(ch for ch in name if ch.isprintable())
    if len(name) > NAME_LIMIT:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: NAME_LIMIT - len(ext) - 1] + dot + ext) if dot else name[:NAME_LIMIT]
    return name or "tailieu.pdf"


def save_upload(source: BinaryIO, dest: Path, max_mb: int) -> None:
    limit = max_mb * 1024 * 1024
    head = source.read(1024)
    if b"%PDF-" not in head:
        raise ApiError(400, "not_pdf")
    size = len(head)
    with dest.open("wb") as out:
        out.write(head)
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ApiError(413, "too_large", mb=max_mb)
            out.write(chunk)


def _check_pending(db: Session, settings: Settings, user_id: str) -> None:
    limit = effective_pending_limit(db, settings)  # DB ghi đè env, đọc MỖI lần (spec §4)
    count = db.scalar(
        select(func.count()).select_from(File).where(File.user_id == user_id, File.status.in_(PENDING))
    ) or 0
    if count >= limit:
        raise ApiError(429, "too_many_pending", limit=limit)


def _check_font(font: str) -> str:
    if font not in PROFILE_IDS:
        raise ApiError(400, "unsupported_font")
    return font


def create_file(db: Session, runner: JobRunner, settings: Settings, user: User,
                filename: str, language: str, source: BinaryIO, *,
                engine: str | None = None, model: str | None = None, font: str | None = None) -> File:
    if language not in VALID_LANGUAGES:
        raise ApiError(400, "unsupported_language")
    font = _check_font(user.default_font if font is None else font)  # không gửi = font mặc định trong Cài đặt
    name = clean_filename(filename)
    if not name.lower().endswith(".pdf"):
        raise ApiError(400, "not_pdf")
    # Kiểm engine/key TRƯỚC khi ghi đĩa: thiếu key thì không có gì để dọn.
    engine_id, model_id = resolve_upload_choice(db, settings.secret_key, user, engine, model)
    _check_pending(db, settings, user.id)
    file_id = uuid.uuid4().hex[:12]
    directory = file_dir(settings.users_dir, user.id, file_id)
    directory.mkdir(parents=True)
    try:
        save_upload(source, directory / safe_name(name), settings.max_upload_mb)
    except ApiError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except OSError as error:
        shutil.rmtree(directory, ignore_errors=True)
        if error.errno == errno.ENOSPC:
            raise ApiError(507, "disk_full") from None
        raise
    row = File(id=file_id, user_id=user.id, filename=name, search_name=normalize_search(name),
               language=language, status="queued", engine=engine_id, model=model_id, font=font)
    try:
        db.add(row)
        db.commit()
    except IntegrityError:
        # Tài khoản đã bị xoá khi tệp đang tải lên (tab/thiết bị khác): khoá ngoại user_id hỏng.
        db.rollback()
        shutil.rmtree(directory, ignore_errors=True)
        raise ApiError(401, "unauthenticated") from None
    runner.enqueue(file_id)
    return row


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(user_id: str, q: str):
    stmt = select(File).where(File.user_id == user_id)
    needle = normalize_search(q.strip())
    if needle:
        stmt = stmt.where(File.search_name.like(f"%{_escape_like(needle)}%", escape="\\"))
    return stmt


# Thứ tự trạng thái khi sắp xếp: đang chờ/đang chạy lên trước, xong sau cùng.
_STATUS_RANK = case({"queued": 0, "running": 1, "error": 2, "done": 3}, value=File.status, else_=4)


def list_files(db: Session, user_id: str, q: str, page: int, page_size: int,
               sort: str = "created", direction: str = "desc") -> tuple[list[File], int]:
    stmt = _filtered(user_id, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    key = {"created": File.created_at, "name": File.search_name.collate("vi"), "status": _STATUS_RANK}[sort]
    # created_at desc, id desc luôn đứng cuối: các trang không trùng/sót khi khoá chính bằng nhau.
    order = [key.asc() if direction == "asc" else key.desc(), File.created_at.desc(), File.id.desc()]
    rows = db.scalars(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    return list(rows), total


def get_owned(db: Session, user_id: str, file_id: str) -> File:
    row = db.get(File, file_id)
    if row is None or row.user_id != user_id:
        raise ApiError(404, "not_found")  # 404 cả khi tệp của người khác: không lộ là có tồn tại
    return row


def to_item(row: File, progress: Progress | None) -> dict:
    done, total, stage = row.done_pages, row.total_pages, row.stage
    if progress is not None and row.status == "running":
        done, total, stage = progress.done, progress.total, progress.stage
    retranslating = row.retranslate_language is not None
    return {
        "id": row.id, "filename": row.filename, "language": row.language, "status": row.status,
        "engine": row.engine, "model": row.model, "stage": stage,
        "done_pages": done, "total_pages": total, "untranslated": row.untranslated, "message": row.message,
        "created_at": iso(row.created_at), "finished_at": iso(row.finished_at),
        "font": row.font, "font_used": row.font_used, "rebuild_font": row.rebuild_font,
        "rebuilding": row.rebuild_font is not None and not retranslating,  # dựng lại FONT (0 lời gọi API)
        "rebuild_error": row.rebuild_error,  # lý do lần dựng lại HOẶC dịch lại gần nhất thất bại
        "retranslating": retranslating,
        "retranslate_to": ({"language": row.retranslate_language, "engine": row.retranslate_engine,
                            "model": row.retranslate_model, "font": row.rebuild_font} if retranslating else None),
    }


def download_target(settings: Settings, row: File, kind: str) -> tuple[Path, str]:
    directory = file_dir(settings.users_dir, row.user_id, row.id)
    if kind == "original":
        path, name = directory / safe_name(row.filename), row.filename
    else:
        # Đang dựng lại / dịch lại tệp đã xong (rebuild_font hoặc retranslate_* khác NULL, tệp queued/running): bản dịch
        # cũ vẫn tải được tới khi bị thay — cùng điều kiện "chạy trong rebuild/" của runner.
        staged = row.rebuild_font is not None or row.retranslate_language is not None
        if (row.status != "done" and not staged) or not row.output_name:
            raise ApiError(409, "not_ready")
        path, name = directory / row.output_name, f"{Path(row.filename).stem}-{row.language}.pdf"
    if not path.is_file():
        raise ApiError(410, "gone")
    return path, name


def rebuild_file(db: Session, runner: JobRunner, settings: Settings, row: File, font: str) -> File:
    """§2.5: dựng lại bản dịch đã xong với hồ sơ font khác. Tệp đi lại qua hàng đợi như một job thường (chiếm một
    chỗ chờ); output_name / font / font_used / untranslated / segments.jsonl giữ nguyên tới khi dựng xong."""
    _check_font(font)
    if row.status != "done":
        raise ApiError(409, "not_rebuildable")
    _check_pending(db, settings, row.user_id)
    # Có điều kiện: hai lượt bấm song song chỉ một lượt được xếp hàng.
    queued = db.execute(update(File).where(File.id == row.id, File.status == "done").values(
        status="queued", rebuild_font=font, rebuild_error="", done_pages=0, total_pages=0, message="", stage="",
    )).rowcount
    db.commit()
    if not queued:
        raise ApiError(409, "not_rebuildable")
    db.refresh(row)
    runner.enqueue(row.id)
    return row


RETRANSLATABLE = ("done", "error")


def resolve_choice(db: Session, settings: Settings, user: User, language: str, engine: str, model: str | None,
                   font: str) -> tuple[str, str, str | None, str]:
    """Bốn lựa chọn của một lượt dịch lại, kiểm như lúc tải lên (400) — TRƯỚC khi đụng tệp nào."""
    if language not in VALID_LANGUAGES:
        raise ApiError(400, "unsupported_language")
    _check_font(font)
    engine_id, model_id = resolve_upload_choice(db, settings.secret_key, user, engine, model)
    return language, engine_id, model_id, font


def _queue_retranslate(db: Session, settings: Settings, row, language: str, engine_id: str, model_id: str | None,
                       font: str) -> bool:
    """Một UPDATE có điều kiện theo trạng thái (spec 2026-10-05 §6). `row` chỉ cần id/status/user_id/output_name (File hoặc Row).
    error → tại chỗ: ghi lựa chọn mới, xoá output cũ, reset — bảng đoạn KHÔNG đụng (worker handoff quyết theo meta).
    done → giữ bản cũ: retranslate_* + rebuild_font trong CÙNG một UPDATE (runner chọn staging theo chúng), bản chính giữ
    tới khi xong. False = trạng thái vừa đổi dưới chân."""
    if row.status == "error":
        old_output = row.output_name  # đọc TRƯỚC: UPDATE đồng bộ luôn đối tượng File trong session (output_name → None)
        queued = db.execute(update(File).where(File.id == row.id, File.status == "error").values(
            status="queued", language=language, engine=engine_id, model=model_id, font=font, message="", output_name=None,
            stage="", done_pages=0, total_pages=0, untranslated=0, started_at=None, finished_at=None, rebuild_error="",
        )).rowcount
        db.commit()
        if queued and old_output:
            (file_dir(settings.users_dir, row.user_id, row.id) / old_output).unlink(missing_ok=True)
        return bool(queued)
    if row.status == "done":
        queued = db.execute(update(File).where(File.id == row.id, File.status == "done").values(
            status="queued", rebuild_font=font, retranslate_language=language, retranslate_engine=engine_id,
            retranslate_model=model_id, rebuild_error="", done_pages=0, total_pages=0, message="", stage="",
        )).rowcount
        db.commit()
        return bool(queued)
    return False


def retranslate_file(db: Session, runner: JobRunner, settings: Settings, user: User, row: File, *, language: str,
                     engine: str, model: str | None, font: str) -> File:
    if row.status not in RETRANSLATABLE:
        raise ApiError(409, "not_retranslatable")
    choice = resolve_choice(db, settings, user, language, engine, model, font)
    _check_pending(db, settings, row.user_id)
    if not _queue_retranslate(db, settings, row, *choice):
        raise ApiError(409, "not_retranslatable")  # hai lượt bấm song song / runner vừa nhận: chỉ một lượt được xếp hàng
    db.refresh(row)
    runner.enqueue(row.id)
    return row


def bulk_retranslate(db: Session, runner: JobRunner, settings: Settings, user: User, *, ids: list[str] | None,
                     q: str = "", choice: dict | None) -> dict:
    """Duyệt theo created_at giảm dần (thứ tự danh sách mặc định): pending → bỏ qua; chạm hạn chờ hiệu lực → bỏ qua, không
    xếp thêm; còn lại theo ngữ nghĩa đơn. `choice` (áp một cài đặt) kiểm MỘT lần trước khi đụng tệp nào; None = giữ cài đặt
    riêng, không kiểm key (thiếu key thì job lỗi như nay). Chỉ chọn cột cần (không nạp File), đọc hết trước vòng lặp."""
    shared = (resolve_choice(db, settings, user, choice["language"], choice["engine"], choice.get("model"), choice["font"])
              if choice is not None else None)
    limit = effective_pending_limit(db, settings)
    pending = db.scalar(select(func.count()).select_from(File).where(File.user_id == user.id, File.status.in_(PENDING))) or 0
    columns = (File.id, File.user_id, File.status, File.language, File.engine, File.model, File.font, File.output_name)
    stmt = (select(*columns).where(File.user_id == user.id, File.id.in_(ids)) if ids is not None
            else _filtered(user.id, q).with_only_columns(*columns))
    rows = db.execute(stmt.order_by(File.created_at.desc(), File.id.desc())).all()
    counts = {"queued": 0, "skipped_pending": 0, "skipped_limit": 0}
    last_queued: str | None = None
    for row in rows:
        if row.status in PENDING:
            counts["skipped_pending"] += 1
            continue
        if pending >= limit:
            counts["skipped_limit"] += 1
            continue
        per_file = shared or (row.language, row.engine, row.model, row.font)
        if _queue_retranslate(db, settings, row, *per_file):
            counts["queued"] += 1
            pending += 1
            last_queued = row.id
        else:
            counts["skipped_pending"] += 1  # đổi trạng thái dưới chân (runner vừa nhận / người khác bấm): coi như đang chờ
    if last_queued is not None:
        runner.enqueue(last_queued)  # chỉ đánh thức luồng chạy: DB là hàng đợi, một lần là đủ cho cả loạt
    return {**counts, "limit": limit}


def try_delete_file(db: Session, settings: Settings, user_id: str, file_id: str) -> str:
    """"deleted" | "running" (đang chạy, giữ nguyên) | "gone" (đã bị request khác xoá). Xoá có điều kiện: nếu luồng
    chạy vừa nhận tệp này thì từ chối, không xoá dưới chân nó. DB là hàng đợi: xoá dòng "queued" là đủ để nó không
    bao giờ được chạy. Không đồng bộ session (synchronize_session=False): xoá hàng loạt phải tuyến tính."""
    deleted = db.execute(delete(File).where(File.id == file_id, File.status != "running"),
                         execution_options={"synchronize_session": False}).rowcount
    db.commit()
    if not deleted:
        # rowcount 0 cũng xảy ra khi dòng đã biến mất: đọc lại để phân biệt "đang chạy" với "đã xoá".
        return "running" if db.scalar(select(File.id).where(File.id == file_id)) else "gone"
    shutil.rmtree(file_dir(settings.users_dir, user_id, file_id), ignore_errors=True)
    return "deleted"


def delete_file(db: Session, settings: Settings, row: File) -> None:
    outcome = try_delete_file(db, settings, row.user_id, row.id)
    if outcome == "running":
        raise ApiError(409, "file_running")
    if outcome == "gone":
        raise ApiError(404, "not_found")


def bulk_delete(db: Session, settings: Settings, user_id: str, *, ids: list[str] | None, q: str = "") -> dict:
    """Xoá nhiều tệp của một user. id không thuộc user (hoặc không tồn tại) bị bỏ qua lặng lẽ — không lộ id người khác.
    Chỉ chọn cột id (không nạp File vào session) để mỗi lần xoá không phải đối chiếu với mọi đối tượng đã nạp."""
    if ids is not None:
        stmt = select(File.id).where(File.user_id == user_id, File.id.in_(ids))
    else:
        stmt = _filtered(user_id, q).with_only_columns(File.id)
    outcomes = [try_delete_file(db, settings, user_id, file_id) for file_id in db.scalars(stmt).all()]
    return {"deleted": outcomes.count("deleted"), "skipped_running": outcomes.count("running")}
