#!/usr/bin/env python3
"""Worker giả cho test: nói đúng giao thức stdout của app/engine/worker.py (+ dòng {"font"} của font_worker.py).

Ghi env nhận được vào <thư mục job>/env-seen.json — thư mục chứa tệp nguồn, nên vẫn đúng chỗ khi runner dựng lại
trong thư mục con rebuild/ — KHÔNG in gì nhạy cảm. Hành vi chọn theo tên tệp nguồn: crash / hang / fail / slow /
escape / partial / badprogress / junkprogress / fontline (phát {"font"} theo TRANSLATE_FONT, auto → sans) /
rebuildfail, rebuildhang (chỉ lỗi / đứng khi đang dựng lại; lần dịch đầu chạy bình thường) /
rebuildslow (chỉ khi dựng lại / dịch lại: ngủ thêm 10 s sau dòng tiến độ đầu — E2E kiểm bản cũ vẫn tải được giữa chừng) /
fontjunk (dòng {"font": []} hỏng kiểu) / clobber, tablename, stderrname, previousname (báo tệp kết quả trùng tên tệp nguồn / bảng đoạn /
worker-stderr.log) / tablejunk (ghi đè bảng bằng rác, cần rebuildfail) / tablegrow (chỉ khi dựng lại: bổ sung bảng đoạn trong rebuild/ rồi lỗi, phải có rebuildfail).
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


source, out_dir, language = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
name = source.stem.lower()
rebuilding = out_dir.name == "rebuild"
font = os.environ.get("TRANSLATE_FONT")
(source.parent / "env-seen.json").write_text(json.dumps({
    "font": font,
    "instructions": os.environ.get("TRANSLATE_INSTRUCTIONS"),  # luôn None: chỉ worker handoff nhận biến này
    "argv": sys.argv[1:],
    "has_secret_key": "SECRET_KEY" in os.environ,
    "has_smtp_password": "SMTP_PASSWORD" in os.environ,
    "has_setup_token": "SETUP_TOKEN" in os.environ,
}), encoding="utf-8")
print("log thường của nhân, không phải JSON", flush=True)
if "fontline" in name:
    emit({"font": font if font in ("sans", "serif") else "sans"})
if "fontjunk" in name:
    emit({"font": []})
if rebuilding and "tablegrow" in name:
    for table in ("segments.jsonl", "segments.meta.json"):
        with (out_dir / table).open("a", encoding="utf-8") as stream:
            stream.write("grown\n")
if rebuilding and "tablejunk" in name:
    for table in ("segments.jsonl", "segments.meta.json"):
        (out_dir / table).write_text("JUNK", encoding="utf-8")
if rebuilding and "rebuildfail" in name:
    sys.stderr.write("rebuild boom\n")
    emit({"ok": False, "error": "Dựng lại thất bại (worker giả)."})
    sys.exit(1)
if rebuilding and "rebuildhang" in name:
    emit({"p": 0, "t": 2})
    time.sleep(3600)
if "crash" in name:
    sys.stderr.write("Segmentation fault\n")
    sys.exit(139)
if "hang" in name and "rebuildhang" not in name:
    emit({"p": 0, "t": 2})
    time.sleep(3600)
if "fail" in name and "rebuildfail" not in name:
    emit({"ok": False, "error": "Tệp này là bản scan thành ảnh, không có lớp văn bản nào để dịch."})
    sys.exit(1)
if "badprogress" in name:
    # Tiến độ hợp lệ, rồi "ngủ" một lúc mới ghi file — dùng để kiểm tra tiến trình
    # con bị giết ngay khi có lỗi trong lúc đọc stdout (không kịp chạy tới đây).
    emit({"p": 1, "t": 2})
    time.sleep(3)
    (out_dir / "late-marker.txt").write_text("late")
    sys.exit(0)
if "junkprogress" in name:
    emit({"p": "x", "t": 2})  # dòng tiến độ hỏng kiểu — nhân thật không làm vậy, nhưng phải chịu được
emit({"p": 1, "t": 2})
if rebuilding and "rebuildslow" in name:
    time.sleep(10)
if "slow" in name:
    time.sleep(3)
emit({"p": 2, "t": 2})
if "escape" in name:
    emit({"ok": True, "output": "/etc/hostname", "untranslated": 0})
    sys.exit(0)
for marker, bad_name in (("clobber", source.name), ("tablename", "segments.jsonl"), ("stderrname", "worker-stderr.log"),
                          ("previousname", ".previous")):
    if marker in name:  # tên tệp kết quả mà runner không được phép nhận
        bad = out_dir / bad_name
        if bad.resolve() != source.resolve() and not bad.exists():
            bad.write_bytes(source.read_bytes() + b"\n% clobbered\n")  # khác bản tải lên: ghi đè là test thấy ngay
        emit({"ok": True, "output": str(bad), "untranslated": 0})
        sys.exit(0)
output = out_dir / f"{source.stem}-{language}.pdf"
shutil.copyfile(source, output)
if rebuilding:  # bản dựng lại phải khác bản cũ để test thấy được tệp đã bị thay
    with output.open("ab") as stream:
        stream.write(f"\n% rebuilt font={font}\n".encode())
emit({"ok": True, "output": str(output), "untranslated": 3 if "partial" in name else 0})
