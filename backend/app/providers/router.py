from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.router import client_ip
from ..deps import current_user, get_db
from ..errors import ApiError
from ..models import User
from . import credentials

router = APIRouter(prefix="/api/settings")


class PreferencesBody(BaseModel):
    default_engine: str
    default_model: str | None = None
    default_font: str | None = None  # auto|sans|serif; bỏ qua = giữ nguyên
    advance_mode: bool | None = None  # bỏ qua = giữ nguyên (spec 2026-10-14 §7)
    default_profile: Any = None  # phân biệt bỏ qua / null qua model_fields_set; kiểu lỏng → service trả profile_not_found


class KeyBody(BaseModel):
    api_key: str


def _secret(request: Request) -> str:
    return request.app.state.settings.secret_key


@router.get("")
def get_settings(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return credentials.settings_payload(db, _secret(request), user)


@router.put("/preferences")
def put_preferences(body: PreferencesBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return credentials.set_preferences(db, _secret(request), user, body.default_engine, body.default_model, body.default_font,
                                       advance_mode=body.advance_mode, default_profile=body.default_profile,
                                       default_profile_set="default_profile" in body.model_fields_set)


@router.put("/credentials/{provider}")
def put_credential(provider: str, body: KeyBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    # Mọi lượt đều tính (key đúng, key sai, provider lạ), và kiểm TRƯỚC khi gọi nhà cung cấp.
    state = request.app.state
    if not state.credential_user_throttle.attempt(str(user.id)):
        raise ApiError(429, "too_many_requests")
    # Attempt user → attempt IP → forgive không nguyên tử, nhưng số đếm vẫn đúng; tệ nhất một request song song
    # của cùng tài khoản thấy dư một lượt trong chốc lát.
    if not state.credential_ip_throttle.attempt(client_ip(request)):
        state.credential_user_throttle.forgive(str(user.id))  # bị chặn vì IP, không phải lỗi của tài khoản này
        raise ApiError(429, "too_many_requests")
    return credentials.save_credential(db, _secret(request), user, provider, body.api_key, request.app.state.provider_transport)


@router.delete("/credentials/{provider}", status_code=204)
def delete_credential(provider: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    credentials.delete_credential(db, user, provider)
    return Response(status_code=204)
