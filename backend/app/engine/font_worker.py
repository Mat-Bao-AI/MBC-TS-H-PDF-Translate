#!/usr/bin/env python3
"""Script khởi động mặc định cho `google_free` (DEFAULT_WORKER_CMD): áp hồ sơ font rồi chạy worker.py.

worker.py không đổi một dòng. Ở đây: import app.engine.worker trước (nó đưa UPSTREAM_ROOT vào sys.path, nên
`pdf2zh` nạp từ đúng cây upstream và qua được `_require_core`), đọc TRANSLATE_FONT (auto|sans|serif, runner đặt),
phát dòng {"font": "sans"|"serif"}, gán đè 3 hook font (app.engine.fonts), bọc `translate_pdf` để subset font của
bản dịch (§2.6), rồi gọi `worker.main()`. Giao thức stdout như worker.py, cộng dòng {"font"} và mã lỗi:
    {"ok": false, "error": "<thông điệp>", "code": "font_profile_unsupported" | "font_files_missing"}
kèm đúng một dòng stderr `font_profile code=<mã> detail=<hook / module / kiểu thiếu>` để chẩn đoán.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))  # chạy như script: cần `app` import được

from app.engine import fonts, worker  # noqa: E402  (worker đưa UPSTREAM_ROOT vào sys.path)


def wrap_translate_pdf() -> None:
    """worker.main() import `translate_pdf` lúc chạy (`from translate_pdf import translate_pdf`): thay hàm trong
    module bằng bản dựng xong thì subset. Không nạp được nhân → để worker.main() tự báo lỗi như cũ."""
    try:
        import translate_pdf as core
    except Exception:  # noqa: BLE001
        return
    original = core.translate_pdf

    def translate_and_subset(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.path is not None and Path(result.path).is_file():
            fonts.subset_pdf(Path(result.path))
        return result

    core.translate_pdf = translate_and_subset


def main(argv: list[str] | None = None, *, run: Callable[[], int] = worker.main,
         prepare: Callable[..., str] = fonts.prepare, wrap: Callable[[], None] = wrap_translate_pdf) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) != 4:
        return run()  # worker.main() tự in cách dùng
    try:
        prepare(os.environ.get("TRANSLATE_FONT", "auto"), Path(argv[1]), worker.emit)
    except Exception as error:  # noqa: BLE001 - lỗi nào ở bước font cũng thành JSON có mã, không traceback trần
        failure = fonts.as_profile_error(error)
        sys.stderr.write(failure.diagnostic + "\n")
        worker.emit({"ok": False, "error": failure.message, "code": failure.code})
        return 1
    wrap()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
