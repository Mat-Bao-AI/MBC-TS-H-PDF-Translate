"""Hồ sơ font cho chữ của bản dịch (spec 2026-10-02 §2).

Ngoài Windows, lõi upstream không tìm được font đậm/nghiêng thật nên làm đậm "giả" bằng viền `2 Tr`, lại còn ưu
tiên Times base-14 cho ký tự ASCII → chữ đậm hai lần, một từ lẫn hai độ đậm. Ở đây, TRONG TIẾN TRÌNH CON và trước
khi gọi `translate_pdf`, ta gán đè đúng ba tên của upstream (không sửa mã upstream):
    pdf2zh.high_level.download_remote_fonts   → font Regular của hồ sơ
    pdf2zh.high_level.output_style_font_paths → 4 tệp khác nhau → không kiểu nào bị coi là "giả" → hết `2 Tr`
    pdf2zh.converter.BASE14_STYLE_FONTS       → tên không có trong fontmap → không bao giờ chọn base-14
Có kiểm tra cứng trước khi gán: nâng pin upstream làm đổi tên/kiểu một hook → `font_profile_unsupported` (stderr
ghi hook / module nào hỏng), không bao giờ âm thầm dựng ra PDF sai. Module này được tiến trình web import
(PROFILE_IDS), nên PyMuPDF / pdf2zh chỉ được import BÊN TRONG hàm.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

PROFILE_IDS: tuple[str, ...] = ("auto", "sans", "serif")  # auto = chọn theo bản gốc (§2.4)
FONT_DIR = Path("/usr/share/fonts/truetype/liberation")  # gói fonts-liberation trong image
FAMILIES = {"sans": "LiberationSans", "serif": "LiberationSerif"}
FACES = ("Regular", "Bold", "Italic", "BoldItalic")  # thứ tự = mã kiểu 0..3 của upstream
SCAN_PAGES = 30
SERIF_WORDS = ("times", "serif", "georgia", "cambria", "garamond", "palatino", "bookantiqua", "minion",
               "baskerville", "bodoni", "century")
SERIF_FLAG = 4  # bit "serifed" trong span["flags"] của PyMuPDF
SANS_WORDS = ("sans", "gothic")  # "Century Gothic" chứa "century" nhưng là không chân
NO_BASE14 = "__no_base14__"
# Như LARGE_DOCUMENT_SUBSET_PAGE_LIMIT của upstream (`page_count >= 200`): tài liệu từ 200 trang thì bỏ qua subset.
SUBSET_PAGE_LIMIT = 200
# Bản nháp tiếng Việt — BA duyệt câu chữ.
ERROR_MESSAGES = {
    "font_profile_unsupported": "Không áp được font cho bản dịch vì nhân dịch đã thay đổi. Báo quản trị viên.",
    "font_files_missing": "Máy chủ thiếu tệp font của bản dịch. Báo quản trị viên.",
}


class FontProfileError(Exception):
    """Không áp được hồ sơ font. `code` chọn câu cho người dùng (ERROR_MESSAGES); `detail` chỉ để chẩn đoán trên
    stderr: `import:<lớp lỗi>:<module>[:<module phụ thuộc thiếu>]`, `hook:<tên>:missing|not-callable|not-dict|keys`,
    `files:<hồ sơ>:<kiểu,…>`, `error:<lớp lỗi>` — chỉ tên module / hook / kiểu / lớp lỗi, không đường dẫn, không bí mật."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} {detail}")
        self.code = code
        self.detail = detail

    @property
    def message(self) -> str:
        return ERROR_MESSAGES[self.code]

    @property
    def diagnostic(self) -> str:
        """Dòng stderr duy nhất của lỗi hồ sơ (runner giữ đuôi stderr để chẩn đoán)."""
        return f"font_profile code={self.code} detail={self.detail}"


def as_profile_error(error: Exception) -> FontProfileError:
    """Lỗi bất kỳ ở bước font (vd PermissionError khi kiểm tệp) → lỗi có mã như mọi lỗi hồ sơ, để worker phát dòng
    `{"ok": false, "code"}` thay vì traceback trần. Chỉ giữ tên lớp lỗi: thông điệp gốc có thể chứa đường dẫn."""
    if isinstance(error, FontProfileError):
        return error
    return FontProfileError("font_profile_unsupported", f"error:{type(error).__name__}")


def _stderr(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def profile_faces(profile: str, font_dir: Path = FONT_DIR) -> dict[int, str]:
    """{0: Regular, 1: Bold, 2: Italic, 3: BoldItalic} của hồ sơ `sans` | `serif`."""
    family = FAMILIES[profile]
    return {style: str(font_dir / f"{family}-{face}.ttf") for style, face in enumerate(FACES)}


def classify_font(name: str, flags: int = 0) -> str:
    """§2.4: tên chuẩn hoá (bỏ tiền tố subset `ABCDEF+`, khoảng trắng, gạch; chữ thường). Có chân khi tên KHÔNG
    chứa từ nào của SANS_WORDS và (chứa một từ của SERIF_WORDS hoặc span có cờ serif); còn lại là không chân."""
    normalized = re.sub(r"[\s_-]", "", re.sub(r"^[A-Z]{6}\+", "", name)).lower()
    if any(word in normalized for word in SANS_WORDS):
        return "sans"
    if any(word in normalized for word in SERIF_WORDS) or flags & SERIF_FLAG:
        return "serif"
    return "sans"


def dominant_font(spans: Iterable[tuple[str, int, str]]) -> tuple[str, int] | None:
    """Font có nhiều ký tự không phải khoảng trắng nhất, kèm OR mọi cờ của các span dùng font đó.
    Không có chữ nào, hoặc hai font đứng đầu ngang nhau → None (người gọi coi là `sans`)."""
    counts: Counter[str] = Counter()
    flags: dict[str, int] = {}
    for font, span_flags, text in spans:
        visible = sum(1 for ch in text if not ch.isspace())
        if visible:
            counts[font] += visible
            flags[font] = flags.get(font, 0) | int(span_flags)
    top = counts.most_common(2)
    if not top or (len(top) == 2 and top[0][1] == top[1][1]):
        return None
    return top[0][0], flags[top[0][0]]


def detect_profile(pdf: Path) -> str:
    """`sans` | `serif` theo font chiếm nhiều chữ nhất trong ≤ 30 trang đầu. Mở không được → `sans` (nhân dịch sẽ
    tự báo lỗi thật của tệp, không chết ở bước chọn font)."""
    try:
        import fitz  # PyMuPDF — chỉ có trong image, không có trong backend/.venv

        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001
        return "sans"
    try:
        spans = (
            (str(span.get("font", "")), int(span.get("flags", 0)), str(span.get("text", "")))
            for page in doc.pages(0, min(SCAN_PAGES, doc.page_count))
            for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]  # chỉ chữ, không byte ảnh
            for line in block.get("lines", ())
            for span in line.get("spans", ())
        )
        best = dominant_font(spans)
    except Exception:  # noqa: BLE001
        return "sans"
    finally:
        doc.close()
    return "sans" if best is None else classify_font(*best)


def resolve_profile(choice: str, source: Path, detect: Callable[[Path], str] = detect_profile) -> str:
    """Lựa chọn của người dùng → hồ sơ thực dùng. `sans`/`serif` giữ nguyên; `auto` (và giá trị lạ) → tự nhận."""
    return choice if choice in FAMILIES else detect(source)


def _import_core(name: str) -> object:
    try:
        return importlib.import_module(name)
    except Exception as error:  # noqa: BLE001
        # Ghi cả module phụ thuộc bị thiếu (ImportError.name, chỉ là tên module) — chính là nguyên nhân cần biết.
        missing = getattr(error, "name", None) if isinstance(error, ImportError) else None
        cause = f":{missing}" if missing and missing != name else ""
        raise FontProfileError("font_profile_unsupported", f"import:{type(error).__name__}:{name}{cause}") from error


def _hook_problem(high_level: object, converter: object) -> str | None:
    """None nếu lõi còn đúng các hook cần gán đè (và 4 mã kiểu 0..3); không thì `hook:<tên>:<lỗi>`."""
    for module, name, kind in (
        (high_level, "download_remote_fonts", "callable"),
        (high_level, "output_style_font_paths", "callable"),
        (high_level, "STYLE_FONT_NAMES", "styles"),
        (converter, "BASE14_STYLE_FONTS", "styles"),
    ):
        if not hasattr(module, name):
            return f"hook:{name}:missing"
        value = getattr(module, name)
        if kind == "callable" and not callable(value):
            return f"hook:{name}:not-callable"
        if kind == "styles" and not isinstance(value, dict):
            return f"hook:{name}:not-dict"
        if kind == "styles" and not all(style in value for style in range(len(FACES))):
            return f"hook:{name}:keys"
    return None


def apply_profile(profile: str, font_dir: Path = FONT_DIR) -> None:
    """Gán đè 3 hook của upstream cho hồ sơ `profile`. Ném FontProfileError, không gán gì, nếu thiếu hook / font."""
    faces = profile_faces(profile, font_dir)
    high_level = _import_core("pdf2zh.high_level")
    converter = _import_core("pdf2zh.converter")
    problem = _hook_problem(high_level, converter)
    if problem is not None:
        raise FontProfileError("font_profile_unsupported", problem)
    missing = [FACES[style] for style, path in faces.items() if not Path(path).is_file()]
    if missing:
        raise FontProfileError("font_files_missing", f"files:{profile}:{','.join(missing)}")
    # Nhận mọi cách gọi (chữ ký thật: download_remote_fonts(lang), output_style_font_paths(language, regular_path)).
    high_level.download_remote_fonts = lambda *args, **kwargs: faces[0]
    high_level.output_style_font_paths = lambda *args, **kwargs: dict(faces)
    converter.BASE14_STYLE_FONTS = {style: NO_BASE14 for style in range(len(FACES))}


def prepare(choice: str, source: Path, emit: Callable[[dict], None], *,
            resolve: Callable[[str, Path], str] = resolve_profile,
            apply: Callable[[str], None] = apply_profile) -> str:
    """Ba bước chung của hai worker, theo đúng thứ tự §6: chọn hồ sơ → phát dòng {"font"} → gán đè hook."""
    profile = resolve(choice, source)
    emit({"font": profile})
    apply(profile)
    return profile


def subset_pdf(path: Path, diagnose: Callable[[str], None] = _stderr) -> bool:
    """§2.6: subset mọi font nhúng của bản dịch (`Document.subset_fonts()` xử lý cả tài liệu, gồm các font Liberation
    vừa nhúng). Chỉ thay tệp khi text từng trang trích ra GIỐNG HỆT và tệp nhỏ hơn; tài liệu từ SUBSET_PAGE_LIMIT
    trang thì bỏ qua; mọi lỗi chỉ ghi một dòng stderr và giữ nguyên bản đã dựng (không bao giờ làm job lỗi)."""
    temp = path.with_name(path.name + ".subset.tmp")
    try:
        import fitz

        with fitz.open(path) as doc:
            if doc.page_count >= SUBSET_PAGE_LIMIT:
                diagnose(f"font_subset skipped=large pages={doc.page_count}")
                return False
            before = [page.get_text("text") for page in doc]
            doc.subset_fonts()
            doc.save(temp, garbage=3, deflate=True)
        with fitz.open(temp) as check:
            after = [page.get_text("text") for page in check]
        if after != before:
            diagnose("font_subset skipped=text_changed")
            return False
        if temp.stat().st_size >= path.stat().st_size:
            diagnose("font_subset skipped=not_smaller")
            return False
        os.replace(temp, path)
        return True
    except Exception as error:  # noqa: BLE001
        diagnose(f"font_subset failed={type(error).__name__}")
        return False
    finally:
        temp.unlink(missing_ok=True)
