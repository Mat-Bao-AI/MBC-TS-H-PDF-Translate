from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .errors import ApiError
from .models import User

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


async def require_fetch_header(request: Request, call_next):
    """Chặn CSRF: form HTML của trang khác không tự đặt được header này."""
    if (
        request.method in UNSAFE_METHODS
        and request.url.path.startswith("/api/")
        and request.headers.get("x-requested-with") != "fetch"
    ):
        return JSONResponse({"detail": {"code": "csrf"}}, status_code=403)
    return await call_next(request)


SESSION_COOKIE = "session"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = request.app.state.auth.resolve_session(db, token) if token else None
    if user is None:
        raise ApiError(401, "unauthenticated")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    """Mọi route /api/system/*: chưa đăng nhập vẫn 401 (current_user), người thường 403 (spec 2026-10-05 §12)."""
    if not user.is_admin:
        raise ApiError(403, "admin_required")
    return user
