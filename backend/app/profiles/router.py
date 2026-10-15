"""/api/profiles — hồ sơ dịch của người đang đăng nhập (spec 2026-10-14 §7). Thân kiểm trong service để trả đúng `field`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..deps import current_user, get_db
from ..models import User
from . import service

router = APIRouter(prefix="/api/profiles")


class ProfileBody(BaseModel):
    """Kiểu lỏng, cho phép khoá lạ: service từ chối từng ô với `field` (pydantic chỉ cho `validation` chung)."""

    model_config = ConfigDict(extra="allow")
    name: Any = None


@router.get("")
def list_profiles(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    service.ensure_seeded(db, user)  # người dùng đợt 1 đang bật chế độ: gieo một lần ở lượt đọc đầu (spec 2026-10-15 §5)
    return service.list_profiles(db, user)


@router.post("", status_code=201)
def create_profile(body: ProfileBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.create_profile(db, user, body.model_dump())


@router.post("/restore-presets")
def restore_presets(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Đưa 5 hồ sơ gieo từ mẫu về tên + giá trị gốc, tạo lại mẫu đã xoá (spec 2026-10-15 §5)."""
    return service.restore_presets(db, user)


@router.put("/{profile_id}")
def update_profile(profile_id: str, body: ProfileBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.update_profile(db, user, profile_id, body.model_dump())


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    service.delete_profile(db, user, profile_id)
    return Response(status_code=204)
