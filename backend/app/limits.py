"""Chặn thân request quá cỡ TRƯỚC khi FastAPI đọc nó.

FastAPI phân tích form multipart (spool tệp tạm ra đĩa) và đọc hết thân JSON trước khi chạy
dependency `current_user` — không có lớp này thì ai chỉ cần header X-Requested-With cũng bắt được
máy chủ nhận bao nhiêu byte tuỳ thích. Lớp ASGI thuần này chạy trước routing, cho POST/PUT/PATCH
dưới /api/:
- POST /api/files: phải có phiên đăng nhập hợp lệ (chỉ đọc cookie, chưa đụng byte nào của thân),
  trần = MAX_UPLOAD_MB + 64KB cho phần vỏ multipart. Vượt → 413 too_large.
- Mọi route khác: trần 64KB. Vượt → 413 request_too_large.
Content-Length khai vượt trần → 413 ngay, không đọc. Không khai (chunked) hoặc khai dối → đếm byte
thật lúc app đọc; vượt thì dừng đọc và trả 413 (nếu app chưa kịp bắt đầu phản hồi).
"""

from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .deps import SESSION_COOKIE

log = logging.getLogger("limits")

BODY_METHODS = {"POST", "PUT", "PATCH"}
JSON_LIMIT = 64 * 1024
MULTIPART_OVERHEAD = 64 * 1024
DISCONNECT: Message = {"type": "http.disconnect"}


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # máy chủ HTTP đã từ chối header hỏng; ở đây cứ đếm byte thật
    return None


def _has_session(state, token: str | None) -> bool:
    if not token:
        return False
    with state.session_factory() as db:
        return state.auth.resolve_session(db, token) is not None


async def _reply(scope: Scope, receive: Receive, send: Send, status: int, detail: dict) -> None:
    await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "POST" and scope["path"].rstrip("/") == "/api/files":
            # Đọc settings/auth lúc chạy (không chụp lúc khởi tạo): test và app cùng thấy một nguồn.
            state = scope["app"].state
            mb = state.settings.max_upload_mb
            limit, too_large = mb * 1024 * 1024 + MULTIPART_OVERHEAD, {"code": "too_large", "mb": mb}
            token = HTTPConnection(scope).cookies.get(SESSION_COOKIE)
            if not await run_in_threadpool(_has_session, state, token):
                await _reply(scope, receive, send, 401, {"code": "unauthenticated"})
                return
        else:
            limit, too_large = JSON_LIMIT, {"code": "request_too_large"}

        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await _reply(scope, receive, send, 413, too_large)
            return

        received = 0
        cut_off = started = replied = False

        async def limited_receive() -> Message:
            nonlocal received, cut_off, replied
            if cut_off:
                return DISCONNECT
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    cut_off = True
                    if not started:
                        replied = True  # đặt TRƯỚC khi await: phản hồi của app chen vào lúc này bị nuốt
                        await _reply(scope, receive, send, 413, too_large)
                    # App thấy client "ngắt kết nối" → thôi đọc; phần thân còn lại không được spool.
                    return DISCONNECT
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if replied:
                return  # đã trả 413 thay cho app: bỏ phản hồi muộn của nó (vd 400 "lỗi đọc thân")
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:  # noqa: BLE001
            if not replied:
                raise
            log.debug("Bỏ qua lỗi của app sau khi đã trả 413", exc_info=True)
