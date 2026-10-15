#!/usr/bin/env python3
"""Dịch một PDF bằng nhà cung cấp có API key (Gemini / Cloud Translation), trong tiến trình riêng.

Lõi upstream không gọi được Gemini/Cloud; nó có engine "handoff": lượt 1 ghi mọi đoạn chưa có bản
dịch ra JSONL, lượt 2 đọc bảng {"src","dst"} và dựng PDF. Worker này đứng giữa hai lượt và dịch
các đoạn bằng app.providers.client. Giao thức stdout như worker.py, cộng `stage` và dòng font:
    {"font": "sans"|"serif"}                                 (một lần, trước dòng tiến độ đầu tiên)
    {"stage": "split"|"translate"|"render", "p": n, "t": m}
    {"ok": true, "output": "<đường dẫn>", "untranslated": <số>}
    {"ok": false, "error": "<thông điệp>", "code": <một khoá của ERROR_MESSAGES>}
Key + provider + model + chỉ dẫn văn phong tới qua env TRANSLATE_PROVIDER / TRANSLATE_API_KEY / TRANSLATE_MODEL /
TRANSLATE_INSTRUCTIONS (chuỗi tiếng Anh do runner dựng, chỉ Gemini dùng; sha256 của nó vào segments.meta.json), hồ sơ
font qua TRANSLATE_FONT (auto|sans|serif, xem app.engine.fonts) — không qua argv (ps đọc được), và không bao giờ
được in ra (chỉ dẫn là nội dung người dùng: cũng không ra log/stderr). Lỗi nhà cung cấp → đúng MỘT dòng chẩn đoán
ra stderr: `provider=… http=… status=… reason=…` (mã của Google, không thân lỗi, không key).
Lỗi ở bước font → đúng một dòng `font_profile code=… detail=…` (xem app.engine.fonts.FontProfileError).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))  # chạy như script: cần `app` import được

from app.engine import fonts  # noqa: E402
from app.engine.worker import emit as emit_line, friendly  # noqa: E402  (worker.py cũng đưa UPSTREAM vào sys.path)
from app.providers.client import ProviderError  # noqa: E402

# Bản nháp tiếng Việt — BA duyệt câu chữ. Mỗi mã của app.providers.client một câu.
ERROR_MESSAGES = {
    "invalid_api_key": "API key bị từ chối — kiểm tra lại key trong Cài đặt",
    "api_not_enabled": "API chưa được bật cho project của key này. Bật Cloud Translation API / Generative Language API "
                       "trong Google Cloud Console.",
    "billing_disabled": "Project của key chưa bật thanh toán.",
    "key_restricted": "Key đang bị giới hạn (theo API, IP hoặc website). Bỏ giới hạn hoặc cho phép API này.",
    "rate_limited": "Dịch vụ đang giới hạn tốc độ của key này. Thử lại sau ít phút.",
    "quota_exceeded": "Đã hết hạn mức của API key",
    "model_unavailable": "Model này không còn dùng được. Tải tệp lên lại và chọn model khác.",
    "provider_rejected": "Dịch vụ từ chối yêu cầu. Thử model khác hoặc kiểm tra lại cấu hình key.",
    "provider_unavailable": "Không gọi được dịch vụ dịch. Thử lại sau.",
    **fonts.ERROR_MESSAGES,  # font_profile_unsupported, font_files_missing
}


def _stderr(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def _progress(emit: Callable[[dict], None], stage: str) -> Callable[[int, int], None]:
    last = {"done": -1}
    emit({"stage": stage, "p": 0, "t": 0})  # dòng đầu của mỗi bước: runner đổi thông điệp ngay

    def on_progress(done: int, total: int) -> None:
        if done != last["done"]:  # lõi gọi rất dày; chỉ phát khi số đã xong đổi
            last["done"] = done
            emit({"stage": stage, "p": done, "t": total})

    return on_progress


def _read_segments(path: Path) -> list[str]:
    seen: set[str] = set()
    segments: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        text = json.loads(line).get("src")
        if isinstance(text, str) and text and text not in seen:
            seen.add(text)
            segments.append(text)
    return segments


def _line(src: str, dst: str) -> str:
    return json.dumps({"src": src, "dst": dst}, ensure_ascii=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def instructions_digest(instructions: str) -> str:
    """Dấu vân tay chỉ dẫn trong segments.meta.json: "" khi không có (meta trước 2026-10-14 không có khoá này = "")."""
    return hashlib.sha256(instructions.encode("utf-8")).hexdigest() if instructions else ""


def _resume(table_path: Path, meta_path: Path, meta: dict, segments: list[str]) -> dict[str, str]:
    """Bảng đã dịch (đã trả tiền) của lần chạy trước — chỉ dùng lại khi cùng provider/model/ngôn ngữ/chỉ dẫn.
    Viết lại tệp bảng cho sạch (bỏ dòng dở dang do worker bị giết giữa lúc ghi, bỏ đoạn không còn trong
    tài liệu) TRƯỚC khi ghi meta: trên đĩa, bảng không bao giờ đi kèm meta của một lựa chọn khác."""
    previous: dict[str, str] = {}
    try:
        recorded = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(recorded, dict):
            recorded.setdefault("instructions", "")  # meta cũ không có khoá: nghĩa là "không có chỉ dẫn" — không được bỏ bảng
        if recorded == meta:
            for line in table_path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and isinstance(record.get("src"), str) and isinstance(record.get("dst"), str) \
                        and record["dst"]:
                    previous[record["src"]] = record["dst"]
    except (OSError, ValueError):
        previous = {}  # chưa có / hỏng / khác lựa chọn → dịch lại từ đầu
    wanted = set(segments)
    previous = {src: dst for src, dst in previous.items() if src in wanted}
    _write_atomic(table_path, "".join(_line(src, dst) for src, dst in previous.items()))
    _write_atomic(meta_path, json.dumps(meta, ensure_ascii=False))
    return previous


def run(source: Path, output_dir: Path, language: str, *, provider: str, api_key: str, model: str,
        translate_pdf, translate, emit: Callable[[dict], None], diagnose: Callable[[str], None] = _stderr,
        font: str = "auto", prepare: Callable[..., str] | None = None,
        subset: Callable[[Path], object] | None = None, instructions: str = "") -> int:
    segments_out = output_dir / "segments-out.jsonl"
    segments_in = output_dir / "segments.jsonl"
    meta_path = output_dir / "segments.meta.json"
    try:
        # 0. font: chọn hồ sơ → dòng {"font"} → gán đè hook — TRƯỚC lượt tách (lượt nào của lõi cũng dựng PDF).
        if prepare is not None:
            prepare(font, source, emit)
    except Exception as error:  # noqa: BLE001 - như font_worker: lỗi nào ở bước font cũng thành lỗi có mã
        failure = fonts.as_profile_error(error)
        diagnose(failure.diagnostic)
        emit({"ok": False, "error": failure.message, "code": failure.code})
        return 1
    try:
        # 1. split: lõi chạy lượt 1 vào thư mục tạm, PDF của lượt này bỏ đi — chỉ cần danh sách đoạn.
        with tempfile.TemporaryDirectory(prefix="pass1-", dir=output_dir) as temp:
            translate_pdf(source, Path(temp), target_language=language, overwrite=True, engine="handoff",
                          emit_segments=segments_out, on_progress=_progress(emit, "split"))
        segments = _read_segments(segments_out) if segments_out.is_file() else []
        # 2. translate: dịch bằng nhà cung cấp; đoạn không dịch được thì không vào bảng (lõi giữ nguyên văn).
        # Mỗi lô xong được ghi ngay (flush) vào segments.jsonl: job hỏng giữa chừng / bị giết thì phần đã
        # trả tiền còn đó, "Dịch lại" tệp lỗi (tại chỗ — _queue_retranslate / _recover không xoá tệp này) với cùng
        # provider/model/ngôn ngữ/chỉ dẫn chỉ dịch phần còn thiếu (_resume). Chỉ dẫn vào meta dưới dạng sha256.
        meta = {"provider": provider, "model": model, "target_language": language,
                "instructions": instructions_digest(instructions)}
        table = _resume(segments_in, meta_path, meta, segments)
        missing = [src for src in segments if src not in table]
        if segments:
            report = _progress(emit, "translate")
            already = len(segments) - len(missing)

            def on_progress(done: int, total: int) -> None:
                report(already + done, already + total)

            if not missing:
                on_progress(0, 0)
            else:
                with segments_in.open("a", encoding="utf-8") as stream:

                    def keep(batch: dict[str, str]) -> None:
                        fresh = {src: dst for src, dst in batch.items() if src not in table}
                        table.update(fresh)
                        stream.write("".join(_line(src, dst) for src, dst in fresh.items()))
                        stream.flush()

                    keep(translate(provider, api_key, model, language, missing, on_progress, keep, instructions=instructions))
        # 3. render: lượt 2 với bảng đã dịch, kết quả như worker.py.
        result = translate_pdf(source, output_dir, target_language=language, overwrite=True, engine="handoff",
                               segments=segments_in, on_progress=_progress(emit, "render"))
    except ProviderError as error:
        diagnose(error.diagnostic(provider, secret=api_key))  # runner lưu đuôi stderr (đã che key) để chẩn đoán
        emit({"ok": False, "error": ERROR_MESSAGES.get(error.code, ERROR_MESSAGES["provider_unavailable"]), "code": error.code})
        return 1
    except Exception as error:  # noqa: BLE001 - mọi lỗi đều phải thành JSON; không in key
        emit({"ok": False, "error": friendly(str(error))})
        return 1
    if result.path is None or not Path(result.path).is_file():
        emit({"ok": False, "error": "Nhân dịch báo xong nhưng không có tệp kết quả."})
        return 1
    if subset is not None:
        subset(Path(result.path))  # §2.6: chỉ thay khi text giống hệt và nhỏ hơn; lỗi chỉ ghi stderr
    # Lõi chỉ đếm đoạn nó tự bỏ (không vừa khung, lỗi); đoạn thiếu trong bảng rơi về nguyên văn mà
    # không được đếm → cộng số đoạn provider không dịch được.
    untranslated = int(result.untranslated) + (len(segments) - len(table))
    emit({"ok": True, "output": str(result.path), "untranslated": untranslated})
    return 0


def main() -> int:
    if len(sys.argv) != 4:
        emit_line({"ok": False, "error": "handoff_worker.py <input.pdf> <output_dir> <lang>"})
        return 2
    provider = os.environ.get("TRANSLATE_PROVIDER", "")
    api_key = os.environ.get("TRANSLATE_API_KEY", "")
    model = os.environ.get("TRANSLATE_MODEL", "")
    instructions = os.environ.get("TRANSLATE_INSTRUCTIONS", "")
    if not provider or not api_key:
        emit_line({"ok": False, "error": "Thiếu TRANSLATE_PROVIDER / TRANSLATE_API_KEY trong môi trường của worker."})
        return 2
    source, output_dir, language = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    try:
        from translate_pdf import translate_pdf  # scripts/ của upstream, do worker.py đã đưa vào sys.path
    except Exception as error:  # noqa: BLE001
        emit_line({"ok": False, "error": f"Không nạp được nhân dịch: {error}"})
        return 2
    from app.providers.client import RequestsTransport, translate_segments

    def translate(provider_, api_key_, model_, language_, segments, on_progress, on_batch, instructions=""):
        return translate_segments(provider_, api_key_, model_, language_, segments, transport=RequestsTransport(),
                                  on_progress=on_progress, on_batch=on_batch, instructions=instructions)

    return run(source, output_dir, language, provider=provider, api_key=api_key, model=model,
               translate_pdf=translate_pdf, translate=translate, emit=emit_line,
               font=os.environ.get("TRANSLATE_FONT", "auto"), prepare=fonts.prepare, subset=fonts.subset_pdf,
               instructions=instructions)


if __name__ == "__main__":
    raise SystemExit(main())
