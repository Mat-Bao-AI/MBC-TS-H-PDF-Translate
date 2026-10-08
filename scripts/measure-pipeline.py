#!/usr/bin/env python3
"""Đo RAM / CPU / thời gian của lượt tách + dựng thật (phần nặng của mọi job) — chạy TRONG image, không mạng:

    docker run --rm --network none [--cpus=N] -v "$PWD/scripts:/work/scripts:ro" -v "$PDFS:/work/pdfs:ro" \
        vi-translate-saas:local python /work/scripts/measure-pipeline.py /work/pdfs/<tệp>.pdf [...]

Với mỗi PDF chạy đúng chuỗi của handoff_worker.py, bảng dịch là GIẢ (mỗi đoạn → "Bản dịch: <nguyên văn>", độ dài
xấp xỉ bản gốc; thời gian gọi mạng dịch KHÔNG nằm trong số đo): prepare (chọn + áp hồ sơ font) → split (engine
"handoff", phát đoạn) → rebuild (engine "handoff" với bảng giả) → subset (§2.6). Mỗi phase in một dòng JSON:
wall giây, CPU giây (os.times, gồm tiến trình con), RSS đỉnh của CẢ container (một luồng lấy mẫu mỗi 0.25 s, cộng
VmRSS của mọi /proc/[0-9]*/status — `docker stats` báo 0B ở DinD này; trang dùng chung giữa các tiến trình bị cộng
lặp nên số hơi cao), cpu_ratio = CPU/wall. Mỗi `docker run --rm` là khởi động lạnh: phase đầu tiên gồm cả việc
upstream ghi `<model>.optimized` cạnh doclayout.onnx trong HOME. Mã thoát 0 = mọi bản dựng ra PDF cùng số trang.
Đặt BACKEND_ROOT để kiểm mã backend khác bản trong image.
"""

from __future__ import annotations

import glob
import json
import os
import re
import resource
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

BACKEND = Path(os.environ.get("BACKEND_ROOT", "/app/backend"))
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402

from app.engine import fonts, worker  # noqa: E402,F401  (worker đưa UPSTREAM_ROOT vào sys.path)

INTERVAL = 0.25
MARKER = "Bản dịch:"
_RSS = re.compile(rb"^VmRSS:\s+(\d+)\s+kB", re.M)


def container_rss_kb() -> int:
    total = 0
    for path in glob.glob("/proc/[0-9]*/status"):
        try:
            with open(path, "rb") as stream:
                match = _RSS.search(stream.read())
        except OSError:
            continue  # tiến trình vừa thoát
        if match:
            total += int(match.group(1))
    return total


class Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0
        self._stop = threading.Event()

    def reset(self) -> None:
        self.peak = container_rss_kb()

    def run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, container_rss_kb())
            self._stop.wait(INTERVAL)

    def finish(self) -> int:
        self.peak = max(self.peak, container_rss_kb())
        return self.peak


def cpu_seconds() -> float:
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


def phase(sampler: Sampler, name: str, doc: str, pages: int, fn):
    sampler.reset()
    wall0, cpu0 = time.perf_counter(), cpu_seconds()
    value = fn()
    wall, cpu = time.perf_counter() - wall0, cpu_seconds() - cpu0
    row = {"doc": doc, "pages": pages, "phase": name, "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
           "cpu_ratio": round(cpu / wall, 2) if wall else 0, "peak_rss_mb": round(sampler.finish() / 1024),
           "ncpu_visible": os.cpu_count()}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return value


def main() -> int:
    from translate_pdf import translate_pdf

    if len(sys.argv) < 2:
        print("dùng: measure-pipeline.py <tệp.pdf> [...]", file=sys.stderr)
        return 2
    sampler = Sampler()
    sampler.start()
    idle = container_rss_kb()
    print(json.dumps({"phase": "baseline", "idle_rss_mb": round(idle / 1024)}), flush=True)
    failures = 0
    for arg in sys.argv[1:]:
        source = Path(arg)
        with fitz.open(source) as doc:
            pages = doc.page_count
        work = Path(tempfile.mkdtemp(prefix="measure-pipeline-"))
        try:
            segments_out, table = work / "segments-out.jsonl", work / "segments.jsonl"
            phase(sampler, "prepare", source.name, pages, lambda: fonts.prepare("auto", source, lambda _line: None))
            phase(sampler, "split", source.name, pages, lambda: translate_pdf(
                source, work / "pass1", target_language="vi", overwrite=True, engine="handoff", emit_segments=segments_out))
            sources, seen = [], set()
            for line in segments_out.read_text(encoding="utf-8").splitlines():
                text = json.loads(line).get("src") if line.strip() else None
                if isinstance(text, str) and text and text not in seen:
                    seen.add(text)
                    sources.append(text)
            table.write_text("".join(json.dumps({"src": s, "dst": f"{MARKER} {s}"}, ensure_ascii=False) + "\n"
                                     for s in sources), encoding="utf-8")
            shutil.rmtree(work / "pass1", ignore_errors=True)
            result = phase(sampler, "rebuild", source.name, pages, lambda: translate_pdf(
                source, work / "out", target_language="vi", overwrite=True, engine="handoff", segments=table))
            out = Path(result.path) if result.path else None
            phase(sampler, "subset", source.name, pages, lambda: fonts.subset_pdf(out, lambda _line: None) if out else None)
            out_pages = 0
            if out and out.is_file():
                with fitz.open(out) as doc:
                    out_pages = doc.page_count
            ok = out_pages == pages and bool(sources)
            failures += not ok
            print(json.dumps({"doc": source.name, "phase": "summary", "pages": pages, "out_pages": out_pages,
                              "segments": len(sources), "src_chars": sum(map(len, sources)),
                              "untranslated": int(result.untranslated), "out_bytes": out.stat().st_size if out and out.is_file() else 0,
                              "self_maxrss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
                              "ok": ok}, ensure_ascii=False), flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("MEASURE PIPELINE: " + ("PASSED" if failures == 0 else f"FAILED ({failures})"), flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
