from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """Lỗi nghiệp vụ: trả {"detail": {"code": ..., ...params}}; frontend dịch `code` sang câu chữ."""

    def __init__(self, status: int, code: str, **params: object) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"detail": {"code": exc.code, **exc.params}}, status_code=exc.status)


async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    # Áp cùng khuôn lỗi cho lỗi tham số do FastAPI/pydantic tự sinh (body sai kiểu, JSON hỏng, ...).
    return JSONResponse({"detail": {"code": "validation"}}, status_code=422)


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Route không tồn tại / sai method: cùng khuôn lỗi thay vì {"detail": "Not Found"} mặc định.
    code = _HTTP_CODES.get(exc.status_code, "error")
    return JSONResponse({"detail": {"code": code}}, status_code=exc.status_code, headers=exc.headers)
