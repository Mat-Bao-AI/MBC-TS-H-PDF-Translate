from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import SESSION_COOKIE, current_user, get_db
from ..errors import ApiError
from ..models import User
from ..security import new_token
from ..system.mail import MailSetup, deliver_later, resolve_mail
from ..system.setup import needs_setup
from ..system.store import instance_row
from . import account
from .mailer import Mail
from .service import SESSION_TTL, VERIFY_TTL, AuthService, Issued

router = APIRouter(prefix="/api/auth")
ACCEPTED = {"status": "accepted"}
VERIFY_NONCE_COOKIE = "verify_nonce"
VERIFY_NONCE_PATH = "/api/auth"


class Credentials(BaseModel):
    email: str
    password: str


class EmailBody(BaseModel):
    email: str


class TokenBody(BaseModel):
    token: str


class ResetBody(BaseModel):
    token: str
    password: str


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def throttle_by_ip(request: Request) -> None:
    """Đăng ký / quên mật khẩu / gửi lại thư: chung một hạn mức theo IP (chống spam thư, dò tài khoản)."""
    if not auth_service(request).request_throttle.attempt(client_ip(request)):
        raise ApiError(429, "too_many_requests")


THROTTLED = [Depends(throttle_by_ip)]


def mail_setup(request: Request, db: Session) -> MailSetup:
    return resolve_mail(db, request.app.state.settings, request.app.state.injected_mailer)


def registration_gate(db: Session = Depends(get_db)) -> None:
    """Trước throttle và validate: điều kiện của instance, không phải của người gọi (không tốn hạn mức, không tra gì)."""
    if not instance_row(db).registration_open:
        raise ApiError(403, "registration_closed")


def setup_gate(db: Session = Depends(get_db)) -> None:
    """Chưa có user nào: register/login đều 409 — không ai được chen tạo tài khoản thường trước wizard (spec §12)."""
    if needs_setup(db):
        raise ApiError(409, "setup_required")


def require_mail(request: Request, db: Session = Depends(get_db)) -> None:
    """Quên mật khẩu / gửi lại thư / đổi email: không có đường gửi thư thì 409 TRƯỚC mọi tra cứu, kiểm mật khẩu."""
    if not mail_setup(request, db).enabled:
        raise ApiError(409, "mail_not_configured")


def send_later(request: Request, background: BackgroundTasks, mail: Mail | None) -> None:
    # Gửi sau khi trả phản hồi: SMTP chậm không làm treo request, không lộ nhánh nào có gửi thư; cấu hình giải lúc gửi.
    if mail is not None:
        background.add_task(deliver_later, request.app, mail)


def me_body(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "is_admin": user.is_admin,
            "smtp_notice_dismissed": user.smtp_notice_dismissed}


def signed_in(db: Session, auth: AuthService, user: User) -> JSONResponse:
    response = JSONResponse(me_body(user))
    response.set_cookie(
        SESSION_COOKIE, auth.create_session(db, user), max_age=int(SESSION_TTL.total_seconds()),
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return response


def signed_out(status_code: int) -> Response:
    response = Response(status_code=status_code)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


def _accepted(request: Request, response: Response, background: BackgroundTasks, issued: Issued) -> dict:
    """Thân 202 và cookie verify_nonce luôn cùng một dạng, dù email còn trống, đã có chủ hay bị chặn gửi thư.
    Vừa phát link thì cookie mang nonce của link đó; không phát thì mang nonce mồi ngẫu nhiên, không khớp token
    nào — có/không có cookie từng là cách dò email nào đã đăng ký."""
    send_later(request, background, issued.mail)
    response.set_cookie(
        VERIFY_NONCE_COOKIE, issued.nonce or new_token(), max_age=int(VERIFY_TTL.total_seconds()),
        httponly=True, secure=True, samesite="lax", path=VERIFY_NONCE_PATH,
    )
    return ACCEPTED


@router.post("/register", status_code=202, dependencies=[Depends(setup_gate), Depends(registration_gate), *THROTTLED])
def register(
    body: Credentials, request: Request, response: Response, background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    issued = auth_service(request).register(db, body.email, body.password, mail_enabled=mail_setup(request, db).enabled)
    return _accepted(request, response, background, issued)


@router.post("/verify-email")
def verify_email(body: TokenBody, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    auth = auth_service(request)
    user, same_browser = auth.verify_email(db, body.token, request.cookies.get(VERIFY_NONCE_COOKIE))
    if not same_browser:
        # Link mở ở trình duyệt khác (hoặc link do người khác xin): xác nhận email nhưng KHÔNG đăng
        # nhập — chặn kẻ "đăng ký trước" email nạn nhân rồi để nạn nhân tự đăng nhập vào tài khoản
        # mang mật khẩu của kẻ đó.
        return JSONResponse({"status": "verified"})
    response = signed_in(db, auth, user)
    response.delete_cookie(VERIFY_NONCE_COOKIE, path=VERIFY_NONCE_PATH, secure=True, httponly=True, samesite="lax")
    return response


@router.post("/resend-verification", status_code=202, dependencies=[Depends(require_mail), *THROTTLED])
def resend_verification(
    body: EmailBody, request: Request, response: Response, background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    return _accepted(request, response, background, auth_service(request).resend_verification(db, body.email))


@router.post("/login", dependencies=[Depends(setup_gate)])
def login(body: Credentials, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    auth = auth_service(request)
    return signed_in(db, auth, auth.login(db, body.email, body.password, client_ip(request)))


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_service(request).end_session(db, token)
    return signed_out(204)


@router.post("/forgot-password", status_code=202, dependencies=[Depends(require_mail), *THROTTLED])
def forgot_password(body: EmailBody, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    send_later(request, background, auth_service(request).forgot_password(db, body.email))
    return ACCEPTED


@router.post("/reset-password", status_code=204)
def reset_password(body: ResetBody, request: Request, db: Session = Depends(get_db)) -> Response:
    auth_service(request).reset_password(db, body.token, body.password)
    return signed_out(204)


@router.post("/confirm-email")
def confirm_email(body: TokenBody, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    """Link đổi email trong thư: không cần đăng nhập và KHÔNG tạo phiên (phiên đang có vẫn giữ nguyên)."""
    user, mail = account.confirm_email_change(db, auth_service(request), body.token)
    send_later(request, background, mail)
    return me_body(user)


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return me_body(user)
