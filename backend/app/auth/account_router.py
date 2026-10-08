"""/api/account/* — Cài đặt › Tài khoản. Mọi route cần đăng nhập + header CSRF (middleware chung)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import SESSION_COOKIE, current_user, get_db
from ..models import User
from . import account
from .router import ACCEPTED, auth_service, client_ip, me_body, require_mail, send_later, signed_out

router = APIRouter(prefix="/api/account")


class ProfileBody(BaseModel):
    display_name: str | None = None


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


class PasswordBody(BaseModel):
    password: str


class EmailChangeBody(BaseModel):
    new_email: str
    password: str


@router.put("/profile")
def put_profile(body: ProfileBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return me_body(account.set_display_name(db, user, body.display_name))


@router.post("/notices/smtp/dismiss", status_code=204)
def dismiss_smtp_notice(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    account.dismiss_smtp_notice(db, user)
    return Response(status_code=204)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChangeBody, request: Request, background: BackgroundTasks,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> Response:
    mail = account.change_password(db, auth_service(request), user, body.current_password, body.new_password,
                                   client_ip(request), request.cookies.get(SESSION_COOKIE) or "")
    send_later(request, background, mail)
    return Response(status_code=204)


@router.post("/email", status_code=202, dependencies=[Depends(require_mail)])
def request_email_change(
    body: EmailChangeBody, request: Request, background: BackgroundTasks,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    mail = account.request_email_change(db, auth_service(request), user, body.new_email, body.password, client_ip(request))
    send_later(request, background, mail)
    return ACCEPTED  # y hệt nhau dù email mới đã có người dùng hay chưa


@router.post("/delete", status_code=204)
def delete_account(body: PasswordBody, request: Request, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> Response:
    account.delete_account(db, auth_service(request), request.app.state.settings, user, body.password, client_ip(request))
    return signed_out(204)
