"""/api/setup/* — công khai (header CSRF vẫn bắt buộc cho POST)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.router import THROTTLED, auth_service, signed_in
from ..deps import get_db
from ..errors import ApiError
from . import setup

router = APIRouter(prefix="/api/setup")


class SetupBody(BaseModel):
    display_name: str | None = None
    email: str
    password: str
    setup_token: str | None = None


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)) -> dict:
    return setup.status_payload(db, request.app.state.settings, request.app.state.injected_mailer)


@router.post("", dependencies=THROTTLED)  # cùng hạn mức 10 lượt / 15 phút / IP với đăng ký, quên mật khẩu
def create(body: SetupBody, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    if not setup.needs_setup(db):
        raise ApiError(409, "setup_done")  # đường nhanh; câu INSERT có điều kiện trong create_admin mới là cửa chắn thật
    # base_url: scheme theo X-Forwarded-Proto của proxy (uvicorn --proxy-headers) — ghi làm địa chỉ trang nếu còn trống.
    # Thiếu header Host thì Starlette quay về scope["server"] (vd IP container sau proxy) — địa chỉ đó vô nghĩa với người dùng,
    # nên không ghi (để NULL + cảnh báo trong create_admin).
    base_url = str(request.base_url) if request.headers.get("host") else ""  # "" → recordable_site_url từ chối + cảnh báo
    user = setup.create_admin(db, request.app.state.settings, display_name=body.display_name, email_raw=body.email,
                              password=body.password, setup_token=body.setup_token, base_url=base_url)
    return signed_in(db, auth_service(request), user)  # cookie phiên như /login
