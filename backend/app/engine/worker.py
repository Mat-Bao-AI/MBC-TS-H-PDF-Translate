#!/usr/bin/env python3
"""Chạy đúng một lượt dịch, trong một tiến trình riêng.

Vì sao tách tiến trình thay vì gọi hàm trong luồng: nhân dịch kéo theo
onnxruntime, OpenCV và PyMuPDF — ba thư viện native. Một lần segfault trong
đám đó mà chạy chung tiến trình web thì sập cả máy chủ chứ không chỉ hỏng một
job. Tách ra, sập chỉ còn là một mã thoát khác 0 mà tiến trình cha đọc được.

Nhân upstream (scripts/translate_pdf.py) tự chặn nếu `pdf2zh` được nạp từ nơi
khác cây thư mục của nó — xem `_require_core`. Nên ở đây phải đưa gốc repo
upstream vào sys.path chứ không cài pdf2zh thành package rời.

Giao thức stdout — mỗi dòng một JSON:
    {"p": <đã xong>, "t": <tổng>}                     tiến trình
    {"ok": true, "output": "<đường dẫn>", "untranslated": <số>}
    {"ok": false, "error": "<thông điệp>"}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

UPSTREAM = Path(os.environ.get("UPSTREAM_ROOT", "/app/upstream"))
for entry in (str(UPSTREAM), str(UPSTREAM / "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def friendly(message: str) -> str:
    """Dịch sang tiếng Việt vài lỗi mà người dùng thật sẽ gặp.

    Nhân upstream trả thông điệp tiếng Anh. Ba trường hợp dưới đây là ba thứ
    người dùng gặp nhiều nhất và tự xử được nếu hiểu, nên đáng dịch; phần còn
    lại để nguyên vì dịch máy móc sẽ làm mất chi tiết cần cho việc chẩn đoán.
    """
    lowered = message.lower()
    if "image-only" in lowered or "no text could be extracted" in lowered:
        return (
            "Tệp này là bản scan thành ảnh, không có lớp văn bản nào để dịch. "
            "Công cụ không có OCR — hãy chạy OCR cho PDF trước rồi dịch tệp kết quả."
        )
    if "does not contain a pdf header" in lowered or "must have a .pdf" in lowered:
        return "Tệp tải lên không phải PDF hợp lệ."
    if "dependencies are missing" in lowered or "refusing external pdf core" in lowered:
        return f"Bản cài đặt trong container bị hỏng: {message}"
    return message


def main() -> int:
    if len(sys.argv) != 4:
        emit({"ok": False, "error": "worker.py <input.pdf> <output_dir> <lang>"})
        return 2

    source, output_dir, language = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

    try:
        from translate_pdf import translate_pdf
    except Exception as error:  # noqa: BLE001 - báo nguyên nhân, đừng nuốt
        emit({"ok": False, "error": f"Không nạp được nhân dịch: {error}"})
        return 2

    last_reported = -1

    def on_progress(done: int, total: int) -> None:
        # Nhân gọi callback rất dày. Chỉ phát khi số trang xong thực sự đổi,
        # nếu không stdout thành nút cổ chai của chính việc dịch.
        nonlocal last_reported
        if done != last_reported:
            last_reported = done
            emit({"p": done, "t": total})

    try:
        result = translate_pdf(
            source,
            output_dir,
            target_language=language,
            overwrite=True,
            on_progress=on_progress,
        )
    except Exception as error:  # noqa: BLE001 - mọi lỗi đều phải thành JSON
        emit({"ok": False, "error": friendly(str(error))})
        return 1

    if result.path is None or not Path(result.path).is_file():
        emit({"ok": False, "error": "Nhân dịch báo xong nhưng không có tệp kết quả."})
        return 1

    emit({"ok": True, "output": str(result.path), "untranslated": int(result.untranslated)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
