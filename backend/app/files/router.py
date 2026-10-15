from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Form, Query, Request, Response, UploadFile
from fastapi import File as FileField
from fastapi.responses import FileResponse
from pydantic import BaseModel, StrictBool, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import current_user, get_db
from ..engine.jobs import JobRunner
from ..models import User
from ..profiles import snapshot as snapshots
from ..providers.catalog import engine_items, model_choices
from . import service
from .languages import LANGUAGES

router = APIRouter(prefix="/api")


class RebuildBody(BaseModel):
    font: str


class BasicChoice(BaseModel):
    """Đủ bốn lựa chọn (spec 2026-10-05 §8); `model` null với engine không cần model. Dùng cho `settings` của hàng loạt."""

    model_config = ConfigDict(extra="forbid")
    language: str
    engine: str
    model: str | None = None
    font: str


class RetranslateBody(BasicChoice):
    """Dịch lại đơn: thêm trường nâng cao (spec 2026-10-14 §7) — kiểm trong profiles.snapshot."""

    profile: str | None = None
    style: dict | None = None
    context: str | None = None


class BulkSelection(BaseModel):
    """Đúng một trong hai: `ids` (1..100 id khác nhau) hoặc `all: true` (+ `q`, cùng nghĩa với bộ lọc của danh sách)."""

    model_config = ConfigDict(extra="forbid")
    ids: list[str] | None = Field(None, min_length=1, max_length=100)
    all: StrictBool | None = None  # strict: {"all": 1} không được lọt
    q: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> BulkSelection:
        if self.all is False:
            raise ValueError("all must be true")
        if (self.ids is None) == (self.all is None):
            raise ValueError("ids xor all")
        if self.ids is not None and (self.q is not None or len(set(self.ids)) != len(self.ids)):
            raise ValueError("q only with all; ids must be unique")
        return self


class BulkDeleteBody(BulkSelection):
    pass


class BulkRetranslateBody(BulkSelection):
    settings: BasicChoice | None = None  # null = giữ cài đặt riêng của từng tệp; không nhận trường nâng cao (spec 2026-10-14 §7)


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/meta")
def meta(request: Request, _user: User = Depends(current_user)) -> dict:
    settings = _settings(request)
    return {
        "languages": [{"code": code, "name": name} for code, name in LANGUAGES],
        "default_language": settings.default_target_lang,
        "max_upload_mb": settings.max_upload_mb,
        "source_url": settings.source_url,
        "engines": engine_items(None),
        "gemini_models": model_choices(None),
    }


@router.get("/files")
def list_files(
    request: Request,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["created", "name", "status"] = "created",
    dir: Literal["asc", "desc"] = "desc",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = service.list_files(db, user.id, q, page, page_size, sort, dir)
    runner = _runner(request)
    return {
        "items": [service.to_item(row, runner.progress(row.id)) for row in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/files", status_code=202)
def upload_file(
    request: Request,
    file: UploadFile = FileField(...),
    language: str = Form(...),
    engine: str | None = Form(None),
    model: str | None = Form(None),
    font: str | None = Form(None),
    profile: str | None = Form(None),
    style: str | None = Form(None),
    context: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = service.create_file(db, _runner(request), _settings(request), user, file.filename or "", language, file.file,
                              engine=engine or None, model=model or None, font=font or None,
                              profile=profile or None, style=snapshots.parse_style_form(style), context=context or None)
    return service.to_item(row, None)


@router.post("/files/bulk-delete")
def bulk_delete_files(body: BulkDeleteBody, request: Request, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> dict:
    return service.bulk_delete(db, _settings(request), user.id, ids=body.ids, q=body.q or "")


@router.post("/files/bulk-retranslate")
def bulk_retranslate_files(body: BulkRetranslateBody, request: Request, user: User = Depends(current_user),
                           db: Session = Depends(get_db)) -> dict:
    return service.bulk_retranslate(db, _runner(request), _settings(request), user, ids=body.ids, q=body.q or "",
                                    choice=body.settings.model_dump() if body.settings else None)


@router.get("/files/{file_id}")
def get_file(file_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    row = service.get_owned(db, user.id, file_id)
    return service.to_detail(db, _settings(request), row, _runner(request).progress(row.id))


def _pdf_response(path, name: str, inline: bool) -> FileResponse:
    response = FileResponse(path, media_type="application/pdf", filename=name,
                            content_disposition_type="inline" if inline else "attachment")
    # Trình duyệt không được tự đoán content-type khi hiển thị inline trong <iframe>.
    response.headers["X-Content-Type-Options"] = "nosniff"
    # "Dựng lại" thay bản dịch tại chỗ (cùng URL): không cho trình duyệt giữ bản cũ trong cache. FileResponse không
    # trả 304 nên "no-cache" (hỏi lại theo ETag) cũng tải lại cả tệp — "no-store" bằng chi phí, lại không ghi tài
    # liệu riêng của người dùng xuống cache đĩa.
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/files/{file_id}/download")
def download_file(
    file_id: str,
    request: Request,
    kind: Literal["translated", "original"] = "translated",
    inline: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    row = service.get_owned(db, user.id, file_id)
    path, name = service.download_target(_settings(request), row, kind)
    return _pdf_response(path, name, inline)


@router.get("/files/{file_id}/versions/{version_id}/download")
def download_version(file_id: str, version_id: str, request: Request, inline: bool = False, user: User = Depends(current_user),
                     db: Session = Depends(get_db)) -> FileResponse:
    row = service.get_owned(db, user.id, file_id)  # 404 not_found trước (tệp của người khác không lộ gì)
    version = service.get_version(db, row, version_id)
    path, name = service.version_target(_settings(request), row, version)
    return _pdf_response(path, name, inline)


@router.post("/files/{file_id}/rebuild", status_code=202)
def rebuild_file(file_id: str, body: RebuildBody, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict:
    row = service.get_owned(db, user.id, file_id)
    return service.to_item(service.rebuild_file(db, _runner(request), _settings(request), row, body.font), None)


@router.post("/files/{file_id}/versions/{version_id}/restore", status_code=202)
def restore_version(file_id: str, version_id: str, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict:
    row = service.get_owned(db, user.id, file_id)  # 404 not_found trước (tệp của người khác không lộ gì)
    version = service.get_version(db, row, version_id)
    return service.to_item(service.restore_version(db, _runner(request), _settings(request), row, version), None)


@router.post("/files/{file_id}/retranslate", status_code=202)
def retranslate_file(file_id: str, body: RetranslateBody, request: Request, user: User = Depends(current_user),
                     db: Session = Depends(get_db)) -> dict:
    row = service.get_owned(db, user.id, file_id)
    queued = service.retranslate_file(db, _runner(request), _settings(request), user, row, language=body.language,
                                      engine=body.engine, model=body.model, font=body.font,
                                      profile=body.profile, style=body.style, context=body.context)
    return service.to_item(queued, None)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    row = service.get_owned(db, user.id, file_id)
    service.delete_file(db, _settings(request), row)
    return Response(status_code=204)
