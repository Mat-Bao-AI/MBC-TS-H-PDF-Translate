#!/usr/bin/env python3
"""Kiểm dựng thật hồ sơ font (spec 2026-10-02 §9) — chạy TRONG image, không mạng:

    docker run --rm --network none -v "$PWD/scripts:/work/scripts:ro" vi-translate-saas:local \
        python /work/scripts/font-render-check.py

Sinh hai PDF mẫu bằng PyMuPDF (chữ Times base-14 = có chân, Helvetica = không chân), chạy lượt tách của lõi
(engine "handoff", offline) rồi dựng lại từ một bảng dịch giả với từng hồ sơ `sans` / `serif`. Mỗi bản dựng phải:
0 toán tử viền `2 Tr`, 0 đoạn sót, có chữ của bảng dịch, nhúng font Liberation; `detect_profile` phải nhận đúng
bản gốc; subset (§2.6) chỉ được thay tệp khi text giữ nguyên, và ảnh render 72 dpi trước/sau subset phải giống hệt.
In một dòng JSON mỗi bản dựng, mã thoát 0 = đạt hết.
Đặt BACKEND_ROOT để kiểm mã backend khác bản trong image (vd thư mục backend của working tree được mount vào).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

BACKEND = Path(os.environ.get("BACKEND_ROOT", "/app/backend"))
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402

from app.engine import fonts, worker  # noqa: E402,F401  (worker đưa UPSTREAM_ROOT vào sys.path)

PARAGRAPH = ("Section 1. Introduction. This report describes the quarterly results of the company and the outlook "
             "for the next period. Revenue grew by twelve percent while costs stayed flat. The board approved a new "
             "investment plan for the regional offices, and the audit committee reviewed the risk register in detail.")
MARKER = "Bản dịch:"


def make_pdf(path: Path, regular: str, bold: str) -> Path:
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 110), "Quarterly report", fontsize=18, fontname=bold)
        top = 120
        for _ in range(3):
            page.insert_textbox(fitz.Rect(72, top, 540, top + 120), PARAGRAPH, fontsize=11, fontname=regular)
            top += 130
    doc.save(path)
    doc.close()
    return path


def stroke_ops(path: Path) -> int:
    with fitz.open(path) as doc:
        return sum(len(re.findall(rb"\b2 Tr\b", b"".join(doc.xref_stream(x) or b"" for x in page.get_contents())))
                   for page in doc)


def pixels(path: Path) -> list[bytes]:
    with fitz.open(path) as doc:
        return [page.get_pixmap(dpi=72).samples for page in doc]


def facts(path: Path) -> dict:
    with fitz.open(path) as doc:
        text = "".join(page.get_text("text") for page in doc)
        embedded = sorted({font[3] for page in doc for font in page.get_fonts(full=True)})
    return {"has_translation": MARKER in text, "liberation": any("Liberation" in name for name in embedded),
            "size": path.stat().st_size}


def main() -> int:
    from translate_pdf import translate_pdf

    work = Path(tempfile.mkdtemp(prefix="font-render-check-"))
    failures = 0
    for expected, (regular, bold) in {"serif": ("tiro", "tibo"), "sans": ("helv", "hebo")}.items():
        sample = make_pdf(work / f"{expected}.pdf", regular, bold)
        detected = fonts.detect_profile(sample)
        split_dir = work / f"{expected}-split"
        emitted = work / f"{expected}-segments-out.jsonl"
        translate_pdf(sample, split_dir, target_language="vi", overwrite=True, engine="handoff", emit_segments=emitted)
        sources = [json.loads(line)["src"] for line in emitted.read_text(encoding="utf-8").splitlines() if line.strip()]
        table = work / f"{expected}-segments.jsonl"
        table.write_text("".join(json.dumps({"src": src, "dst": f"{MARKER} {src}"}, ensure_ascii=False) + "\n"
                                 for src in sources), encoding="utf-8")
        if expected == "serif":
            # Đối chứng (chỉ để đọc, không tính đạt/trượt): lõi nguyên bản, CHƯA áp hồ sơ nào → phải thấy `2 Tr`;
            # thấy 0 nghĩa là phép đếm không còn bắt được lỗi cũ (hoặc upstream đã tự sửa) — xem lại phép kiểm.
            baseline = translate_pdf(sample, work / "baseline", target_language="vi", overwrite=True, engine="handoff",
                                     segments=table)
            print(json.dumps({"source": expected, "profile": "baseline-upstream",
                              "stroke_2Tr": stroke_ops(Path(baseline.path))}), flush=True)
        for profile in ("sans", "serif"):
            fonts.apply_profile(profile)
            out = work / f"{expected}-{profile}"
            result = translate_pdf(sample, out, target_language="vi", overwrite=True, engine="handoff", segments=table)
            path = Path(result.path)
            before = facts(path)
            row = {"source": expected, "detected": detected, "profile": profile, "segments": len(sources),
                   "untranslated": int(result.untranslated), "stroke_2Tr": stroke_ops(path), **before}
            notes: list[str] = []
            rendered = pixels(path)
            row["subset"] = fonts.subset_pdf(path, notes.append)
            row["subset_note"] = notes[0] if notes else ""
            after = facts(path)
            row["size_after_subset"] = after["size"]
            row["pixels_same"] = pixels(path) == rendered  # subset không được đổi một điểm ảnh nào
            row["ok"] = (detected == expected and row["segments"] > 0 and row["untranslated"] == 0
                         and row["stroke_2Tr"] == 0 and before["has_translation"] and before["liberation"]
                         and after["has_translation"] and stroke_ops(path) == 0 and row["subset"] and row["pixels_same"])
            failures += not row["ok"]
            print(json.dumps(row, ensure_ascii=False), flush=True)
    print("FONT RENDER CHECK: " + ("PASSED" if failures == 0 else f"FAILED ({failures})"), flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
