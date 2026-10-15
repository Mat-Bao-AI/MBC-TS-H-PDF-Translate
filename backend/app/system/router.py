"""/api/system/* — Cài đặt › Hệ thống. Mọi route qua require_admin (401 chưa đăng nhập, 403 người thường) + header CSRF."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth.mailer import Mailer
from ..config import Settings
from ..deps import get_db, require_admin
from ..errors import ApiError
from ..models import User
from . import service

router = APIRouter(prefix="/api/system", dependencies=[Depends(require_admin)])


class SmtpBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: Any = None  # kiểu lỏng: service kiểm int chặt (từ chối true/"587"/587.5) → invalid_smtp field=port
    security: str
    username: str = ""
    password: str | None = None  # bỏ qua / rỗng = mật khẩu đã lưu của đúng host+security đó (service._password_for)
    from_: str = Field(alias="from")


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    smtp: SmtpBody | None = None
    registration_open: bool | None = None
    max_pending_per_user: Any = None  # phân biệt "bỏ qua" và null qua model_fields_set; kiểu lỏng → service trả invalid_limit
    max_versions: Any = None  # như max_pending_per_user: phân biệt bỏ qua / null qua model_fields_set


class TestMailBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    smtp: SmtpBody | None = None


def _ctx(request: Request) -> tuple[Settings, Mailer | None]:
    return request.app.state.settings, request.app.state.injected_mailer


def _smtp(body: SmtpBody | None) -> dict | None:
    return None if body is None else body.model_dump(by_alias=True)


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)) -> dict:
    return service.settings_payload(db, *_ctx(request))


@router.put("/settings")
def put_settings(body: SettingsBody, request: Request, db: Session = Depends(get_db)) -> dict:
    return service.update_settings(db, *_ctx(request), smtp=_smtp(body.smtp), registration_open=body.registration_open,
                                   max_pending=body.max_pending_per_user,
                                   max_pending_set="max_pending_per_user" in body.model_fields_set,
                                   max_versions=body.max_versions, max_versions_set="max_versions" in body.model_fields_set)


@router.delete("/settings/smtp", status_code=204)
def delete_smtp(db: Session = Depends(get_db)) -> Response:
    service.clear_smtp(db)
    return Response(status_code=204)


@router.post("/smtp/test")
def test_smtp(request: Request, body: TestMailBody | None = None, user: User = Depends(require_admin),
              db: Session = Depends(get_db)) -> dict:
    # 6 lượt/phút cho MỖI admin, tách khỏi mail_throttle 60 s/địa chỉ (thư thử là của admin, không phải thư hệ thống).
    if not request.app.state.test_mail_throttle.attempt(str(user.id)):
        raise ApiError(429, "too_many_requests")
    return {"sent_to": service.send_test_mail(db, *_ctx(request), user, _smtp(body.smtp if body else None))}
