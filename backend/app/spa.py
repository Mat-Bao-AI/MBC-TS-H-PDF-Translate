from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .errors import ApiError

# python:3.12-slim không có /etc/mime.types: không đăng ký thì font tự host ra text/plain.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Phục vụ bản build React. Đăng ký SAU mọi router API để /api và /health luôn thắng."""
    root = static_dir.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        if path == "assets" or path.startswith("assets/"):
            # Tệp tĩnh không có (vd chunk của bản build cũ): 404 thật, không trả trang HTML với mã 200.
            raise ApiError(404, "not_found")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
