#!/usr/bin/env python3
"""Worker handoff giả: nói giao thức stdout của app/engine/handoff_worker.py (có `stage`, dòng {"font"}).

Ghi env nhận được vào <thư mục job>/env-seen.json (thư mục chứa tệp nguồn — đúng chỗ cả khi dựng lại trong
rebuild/) để test kiểm — KHÔNG in key ra stdout/stderr, trừ tên tệp "leaky" (cố tình, để kiểm runner có che key
trong message lưu DB hay không). `table_seen` = thư mục ra có sẵn segments.jsonl (runner chép bảng vào rebuild/);
`out_dir_listing` = tên các mục trong thư mục ra lúc worker bắt đầu (runner đã dọn rebuild/ thế nào).
Hành vi theo tên tệp: fail (key bị từ chối) / slow (ngủ 3 s ở bước dịch) / hang (đứng ở bước dịch, đoạn 3/10, tới
khi bị giết) / weirdstage (phát một stage lạ mà worker thật không bao giờ gửi, runner phải lọc bỏ) / leaky (làm lộ
key ra stderr + "error" — runner phải che trước khi lưu) / fontline (phát {"font"}) / rebuildfail (chỉ lỗi khi
đang dựng lại) / gone (Google đã gỡ model: lỗi code=model_unavailable) / newtable (chỉ khi dựng lại/dịch lại: ghi bảng
đoạn MỚI + meta của lựa chọn hiện tại vào thư mục ra, trước mọi marker khác).
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
api_key = os.environ.get("TRANSLATE_API_KEY") or ""
rebuilding = out_dir.name == "rebuild"
font = os.environ.get("TRANSLATE_FONT")
(source.parent / "env-seen.json").write_text(json.dumps({
    "provider": os.environ.get("TRANSLATE_PROVIDER"),
    "model": os.environ.get("TRANSLATE_MODEL"),
    "font": font,
    "api_key": api_key,
    "argv": sys.argv[1:],
    "table_seen": (out_dir / "segments.jsonl").is_file(),
    "out_dir_listing": sorted(child.name for child in out_dir.iterdir()),
    "has_secret_key": "SECRET_KEY" in os.environ,
    "has_smtp_password": "SMTP_PASSWORD" in os.environ,
    "has_setup_token": "SETUP_TOKEN" in os.environ,
}), encoding="utf-8")
print("log thường của worker handoff, không phải JSON", flush=True)
name = source.stem.lower()
if rebuilding and "newtable" in name:  # dịch lại từ đầu: worker ghi bảng đoạn của lựa chọn MỚI vào rebuild/
    (out_dir / "segments.jsonl").write_text('{"src": "x", "dst": "y"}\n', encoding="utf-8")
    (out_dir / "segments.meta.json").write_text(json.dumps({
        "provider": os.environ.get("TRANSLATE_PROVIDER"), "model": os.environ.get("TRANSLATE_MODEL"), "target_language": language,
    }), encoding="utf-8")
if "fontline" in name:
    emit({"font": font if font in ("sans", "serif") else "sans"})
if rebuilding and "rebuildfail" in name:
    emit({"ok": False, "error": "Dựng lại thất bại (worker giả).", "code": "provider_unavailable"})
    sys.exit(1)
if "gone" in name:
    emit({"ok": False, "error": "Model này không còn dùng được. Tải tệp lên lại và chọn model khác.",
          "code": "model_unavailable"})
    sys.exit(1)
if "leaky" in name:
    sys.stderr.write(f"debug: request failed, key was {api_key}\n")
    emit({"ok": False, "error": f"request failed with key {api_key}", "code": "invalid_api_key"})
    sys.exit(1)
if "fail" in name and "rebuildfail" not in name:
    emit({"ok": False, "error": "API key bị từ chối — kiểm tra lại key trong Cài đặt", "code": "invalid_api_key"})
    sys.exit(1)
if "weirdstage" in name:
    emit({"stage": "mystery", "p": 1, "t": 9})  # worker thật không bao giờ gửi stage này
    time.sleep(1)  # cho test kịp đọc DB trước khi job chạy tiếp
emit({"stage": "split", "p": 0, "t": 0})
emit({"stage": "split", "p": 2, "t": 2})
if "hang" in name:  # đứng ở bước dịch (đoạn 3/10) tới khi bị watchdog giết
    emit({"stage": "translate", "p": 3, "t": 10})
    time.sleep(30)
emit({"stage": "translate", "p": 0, "t": 5})
if "slow" in name:
    time.sleep(3)
emit({"stage": "translate", "p": 5, "t": 5})
emit({"stage": "render", "p": 0, "t": 0})
emit({"stage": "render", "p": 2, "t": 2})
output = out_dir / f"{source.stem}-{language}.pdf"
shutil.copyfile(source, output)
if rebuilding:
    with output.open("ab") as stream:
        stream.write(f"\n% rebuilt font={font}\n".encode())
emit({"ok": True, "output": str(output), "untranslated": 1})
