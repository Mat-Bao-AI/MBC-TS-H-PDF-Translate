import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from app.engine import font_worker, fonts
from app.engine.fonts import NO_BASE14, FontProfileError
from helpers import PDF

LIBERATION = Path("/usr/share/fonts/truetype/liberation")


def font_dir(tmp_path, profile="sans") -> Path:
    """Thư mục font giả đủ 4 tệp của hồ sơ — test không cần gói fonts-liberation."""
    folder = tmp_path / "fonts"
    folder.mkdir(exist_ok=True)
    for path in fonts.profile_faces(profile, folder).values():
        Path(path).write_bytes(b"ttf")
    return folder


def fake_core(monkeypatch, **overrides):
    """Module pdf2zh giả trong sys.modules, đủ ba hook như upstream ae156cf2 (ghi đè từng tên qua `overrides`)."""
    package, high_level, converter = ModuleType("pdf2zh"), ModuleType("pdf2zh.high_level"), ModuleType("pdf2zh.converter")
    high_level.download_remote_fonts = lambda lang: "/app/GoNotoKurrent-Regular.ttf"
    high_level.output_style_font_paths = lambda lang, regular: {style: regular for style in range(4)}
    high_level.STYLE_FONT_NAMES = {0: "noto", 1: "noto-bold", 2: "noto-italic", 3: "noto-bolditalic"}
    converter.BASE14_STYLE_FONTS = {0: "tiro", 1: "tibo", 2: "tiit", 3: "tibi"}
    for name, value in overrides.items():
        module = converter if name == "BASE14_STYLE_FONTS" else high_level
        if value is None:
            delattr(module, name)
        else:
            setattr(module, name, value)
    package.high_level, package.converter = high_level, converter
    monkeypatch.setitem(sys.modules, "pdf2zh", package)
    monkeypatch.setitem(sys.modules, "pdf2zh.high_level", high_level)
    monkeypatch.setitem(sys.modules, "pdf2zh.converter", converter)
    return high_level, converter


def test_profile_faces_point_at_the_four_liberation_faces():
    assert fonts.profile_faces("sans") == {
        0: str(LIBERATION / "LiberationSans-Regular.ttf"), 1: str(LIBERATION / "LiberationSans-Bold.ttf"),
        2: str(LIBERATION / "LiberationSans-Italic.ttf"), 3: str(LIBERATION / "LiberationSans-BoldItalic.ttf"),
    }
    assert fonts.profile_faces("serif")[3] == str(LIBERATION / "LiberationSerif-BoldItalic.ttf")
    assert fonts.PROFILE_IDS == ("auto", "sans", "serif")


@pytest.mark.parametrize(("name", "flags", "expected"), [
    ("ABCDEF+TimesNewRomanPSMT", 0, "serif"),
    ("Times-Roman", 0, "serif"),
    ("Georgia-Bold", 0, "serif"),
    ("Book Antiqua", 0, "serif"),
    ("MinionPro-Regular", 0, "serif"),
    ("UnknownFace", 4, "serif"),  # cờ serif của PyMuPDF
    ("ArialMT", 0, "sans"),
    ("CenturyGothic-Bold", 0, "sans"),  # chứa "century" nhưng "gothic" thắng
    ("PT_Sans-Web", 0, "sans"),
    ("DejaVu Sans Serif", 4, "sans"),  # chứa "sans" thì luôn là không chân, kể cả có cờ serif
    ("UnknownFace", 0, "sans"),
])
def test_classify_font(name, flags, expected):
    assert fonts.classify_font(name, flags) == expected


def test_dominant_font_counts_visible_characters():
    spans = [("Arial", 0, "a   b"), ("Times", 4, "abc"), ("Arial", 0, "  "), ("Times", 0, "d")]
    assert fonts.dominant_font(spans) == ("Times", 4)  # 4 chữ thấy được với Times, 2 với Arial; cờ OR lại


def test_dominant_font_is_none_without_text_or_on_a_tie():
    assert fonts.dominant_font([]) is None
    assert fonts.dominant_font([("Arial", 0, "   ")]) is None
    assert fonts.dominant_font([("Arial", 0, "ab"), ("Times", 4, "cd")]) is None


def test_resolve_profile_keeps_an_explicit_choice_and_detects_for_auto(tmp_path):
    seen = []

    def detect(path):
        seen.append(path)
        return "serif"

    assert fonts.resolve_profile("sans", tmp_path / "a.pdf", detect) == "sans"
    assert fonts.resolve_profile("serif", tmp_path / "a.pdf", detect) == "serif"
    assert seen == []  # chọn rõ thì không mở bản gốc
    assert fonts.resolve_profile("auto", tmp_path / "a.pdf", detect) == "serif"
    assert fonts.resolve_profile("comic", tmp_path / "a.pdf", detect) == "serif"  # giá trị lạ = auto
    assert seen == [tmp_path / "a.pdf"] * 2


def test_apply_profile_sets_the_three_hooks(monkeypatch, tmp_path):
    high_level, converter = fake_core(monkeypatch)
    folder = font_dir(tmp_path, "serif")
    fonts.apply_profile("serif", folder)
    faces = fonts.profile_faces("serif", folder)
    assert high_level.download_remote_fonts("vi") == faces[0]
    assert high_level.output_style_font_paths("vi", "/whatever.ttf") == faces
    # Gọi bằng tên tham số như chữ ký thật của upstream cũng không được TypeError.
    assert high_level.download_remote_fonts(lang="vi") == faces[0]
    assert high_level.output_style_font_paths(language="vi", regular_path="/whatever.ttf") == faces
    assert len(set(faces.values())) == 4  # 4 tệp khác nhau → upstream không coi kiểu nào là "giả" → không `2 Tr`
    assert converter.BASE14_STYLE_FONTS == {style: NO_BASE14 for style in range(4)}
    assert high_level.STYLE_FONT_NAMES == {0: "noto", 1: "noto-bold", 2: "noto-italic", 3: "noto-bolditalic"}


def hook_snapshot(high_level, converter) -> tuple:
    return tuple(getattr(module, name, None) for module, name in (
        (high_level, "download_remote_fonts"), (high_level, "output_style_font_paths"),
        (converter, "BASE14_STYLE_FONTS")))


@pytest.mark.parametrize(("broken", "detail"), [
    ({"download_remote_fonts": None}, "hook:download_remote_fonts:missing"),
    ({"output_style_font_paths": "not callable"}, "hook:output_style_font_paths:not-callable"),
    ({"STYLE_FONT_NAMES": {0: "noto", 1: "noto-bold", 2: "noto-italic"}}, "hook:STYLE_FONT_NAMES:keys"),
    ({"STYLE_FONT_NAMES": None}, "hook:STYLE_FONT_NAMES:missing"),
    ({"BASE14_STYLE_FONTS": ("tiro", "tibo", "tiit", "tibi")}, "hook:BASE14_STYLE_FONTS:not-dict"),
    ({"BASE14_STYLE_FONTS": None}, "hook:BASE14_STYLE_FONTS:missing"),
    ("no-core", "import:ModuleNotFoundError:pdf2zh.high_level"),
    ("no-converter", "import:ModuleNotFoundError:pdf2zh.converter"),
])
def test_apply_profile_refuses_a_core_without_the_hooks(monkeypatch, tmp_path, broken, detail):
    if broken == "no-core":
        monkeypatch.setitem(sys.modules, "pdf2zh.high_level", None)  # import ném ImportError
        before = None
    elif broken == "no-converter":
        high_level, converter = fake_core(monkeypatch)
        monkeypatch.setitem(sys.modules, "pdf2zh.converter", None)
        before = hook_snapshot(high_level, converter)
    else:
        high_level, converter = fake_core(monkeypatch, **broken)
        before = hook_snapshot(high_level, converter)
    with pytest.raises(FontProfileError) as caught:
        fonts.apply_profile("sans", font_dir(tmp_path))
    assert caught.value.code == "font_profile_unsupported"
    assert caught.value.message == "Không áp được font cho bản dịch vì nhân dịch đã thay đổi. Báo quản trị viên."
    assert caught.value.detail == detail  # hook / module nào hỏng — ghi ra stderr để chẩn đoán khi nâng pin upstream
    if before is not None:  # không gán dở dang chỗ nào
        assert hook_snapshot(high_level, converter) == before


def test_apply_profile_names_the_dependency_the_core_failed_to_import(monkeypatch, tmp_path):
    def broken_import(name):
        raise ModuleNotFoundError("No module named 'onnxruntime'", name="onnxruntime")

    monkeypatch.setattr(fonts.importlib, "import_module", broken_import)
    with pytest.raises(FontProfileError) as caught:
        fonts.apply_profile("sans", font_dir(tmp_path))
    assert caught.value.code == "font_profile_unsupported"
    assert caught.value.detail == "import:ModuleNotFoundError:pdf2zh.high_level:onnxruntime"


def test_apply_profile_refuses_missing_font_files(monkeypatch, tmp_path):
    high_level, converter = fake_core(monkeypatch)
    folder = font_dir(tmp_path)
    Path(fonts.profile_faces("sans", folder)[3]).unlink()
    with pytest.raises(FontProfileError) as caught:
        fonts.apply_profile("sans", folder)
    assert caught.value.code == "font_files_missing"
    assert caught.value.detail == "files:sans:BoldItalic"  # tên kiểu, không phải đường dẫn
    assert converter.BASE14_STYLE_FONTS == {0: "tiro", 1: "tibo", 2: "tiit", 3: "tibi"}


def test_prepare_resolves_then_announces_then_applies(tmp_path):
    order = []
    profile = fonts.prepare(
        "auto", tmp_path / "a.pdf", lambda line: order.append(("emit", line)),
        resolve=lambda choice, source: order.append(("resolve", choice)) or "serif",
        apply=lambda chosen: order.append(("apply", chosen)),
    )
    assert profile == "serif"
    assert order == [("resolve", "auto"), ("emit", {"font": "serif"}), ("apply", "serif")]


def test_subset_never_raises_and_keeps_the_file(tmp_path):
    broken = tmp_path / "doc-vi.pdf"
    broken.write_bytes(b"not a pdf")
    lines = []
    assert fonts.subset_pdf(broken, lines.append) is False
    assert broken.read_bytes() == b"not a pdf"
    assert len(lines) == 1 and lines[0].startswith("font_subset failed=")
    assert list(tmp_path.iterdir()) == [broken]  # không sót tệp tạm


def fake_fitz(monkeypatch, doc) -> None:
    """PyMuPDF giả: `fitz.open(...)` trả `doc` — chạy được cả trong backend/.venv."""
    module = ModuleType("fitz")
    module.TEXTFLAGS_TEXT = 195  # giá trị thật của PyMuPDF 1.25: không có TEXT_PRESERVE_IMAGES
    module.open = lambda path: doc
    monkeypatch.setitem(sys.modules, "fitz", module)


def test_subset_skips_documents_from_the_upstream_page_limit(monkeypatch, tmp_path):
    class Doc:  # đúng 200 trang = LARGE_DOCUMENT_SUBSET_PAGE_LIMIT của upstream (`page_count >= 200`)
        page_count = fonts.SUBSET_PAGE_LIMIT

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def subset_fonts(self):
            raise AssertionError("tài liệu dài không được subset")

    fake_fitz(monkeypatch, Doc())
    path = tmp_path / "doc-vi.pdf"
    path.write_bytes(PDF)
    lines = []
    assert fonts.subset_pdf(path, lines.append) is False
    assert lines == ["font_subset skipped=large pages=200"]
    assert path.read_bytes() == PDF and list(tmp_path.iterdir()) == [path]


def test_detect_profile_reads_only_the_text_of_the_first_pages(monkeypatch, tmp_path):
    seen = []

    class Page:
        def get_text(self, kind, flags=None):
            seen.append((kind, flags))
            return {"blocks": [{"type": 1}, {"lines": [{"spans": [{"font": "Times-Roman", "flags": 0, "text": "abc"}]}]}]}

    class Doc:
        page_count = 45

        def pages(self, start, stop):
            seen.append(("pages", start, stop))
            return (Page() for _ in range(start, stop))

        def close(self):
            seen.append("close")

    fake_fitz(monkeypatch, Doc())
    assert fonts.detect_profile(tmp_path / "a.pdf") == "serif"
    assert seen[0] == ("pages", 0, 30) and seen[-1] == "close"
    assert seen[1:-1] == [("dict", 195)] * 30  # chỉ chữ: không trích byte ảnh của 30 trang


# ---- font_worker.py (script khởi động cho google_free) -------------------------------------------

def test_font_worker_prepares_the_profile_then_runs_the_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSLATE_FONT", "serif")
    calls = []
    code = font_worker.main(
        ["font_worker.py", str(tmp_path / "doc.pdf"), str(tmp_path), "vi"],
        run=lambda: calls.append("run") or 0,
        prepare=lambda choice, source, emit: calls.append(("prepare", choice, source)) or "serif",
        wrap=lambda: calls.append("wrap"),
    )
    assert code == 0
    assert calls == [("prepare", "serif", tmp_path / "doc.pdf"), "wrap", "run"]


def test_font_worker_reports_a_profile_error_as_coded_json(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TRANSLATE_FONT", raising=False)
    seen, ran = [], []

    def failing(choice, source, emit):
        seen.append(choice)
        raise FontProfileError("font_files_missing", "files:sans:Bold")

    code = font_worker.main(["font_worker.py", str(tmp_path / "doc.pdf"), str(tmp_path), "vi"],
                            run=lambda: ran.append(1) or 0, prepare=failing, wrap=lambda: None)
    out, err = capsys.readouterr()
    assert code == 1 and ran == [] and seen == ["auto"]  # không có TRANSLATE_FONT → auto; lỗi thì không chạy nhân
    assert json.loads(out.strip().splitlines()[-1]) == {
        "ok": False, "error": "Máy chủ thiếu tệp font của bản dịch. Báo quản trị viên.", "code": "font_files_missing"}
    assert err.strip() == "font_profile code=font_files_missing detail=files:sans:Bold"


def test_font_worker_turns_any_other_prepare_error_into_a_coded_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TRANSLATE_FONT", "sans")
    ran = []

    def failing(choice, source, emit):
        raise PermissionError(13, "Permission denied", str(LIBERATION / "LiberationSans-Bold.ttf"))

    code = font_worker.main(["font_worker.py", str(tmp_path / "doc.pdf"), str(tmp_path), "vi"],
                            run=lambda: ran.append(1) or 0, prepare=failing, wrap=lambda: ran.append("wrap"))
    out, err = capsys.readouterr()
    assert code == 1 and ran == []
    assert json.loads(out.strip().splitlines()[-1]) == {
        "ok": False, "error": fonts.ERROR_MESSAGES["font_profile_unsupported"], "code": "font_profile_unsupported"}
    assert err.strip() == "font_profile code=font_profile_unsupported detail=error:PermissionError"
    assert str(LIBERATION) not in out + err  # thông điệp gốc (có đường dẫn) không lọt ra


def test_font_worker_with_the_real_profile_code_refuses_a_changed_core(monkeypatch, tmp_path, capsys):
    fake_core(monkeypatch, BASE14_STYLE_FONTS=None)  # như một lần nâng pin upstream đổi tên hook
    monkeypatch.setenv("TRANSLATE_FONT", "sans")  # chọn rõ → không mở bản gốc
    ran = []
    code = font_worker.main(["font_worker.py", str(tmp_path / "doc.pdf"), str(tmp_path), "vi"],
                            run=lambda: ran.append("run") or 0, wrap=lambda: ran.append("wrap"))  # prepare thật
    out, err = capsys.readouterr()
    assert code == 1 and ran == []  # nhân dịch không bao giờ chạy với hook chưa gán
    assert [json.loads(line) for line in out.strip().splitlines()] == [
        {"font": "sans"},
        {"ok": False, "error": fonts.ERROR_MESSAGES["font_profile_unsupported"], "code": "font_profile_unsupported"},
    ]
    assert err.strip() == "font_profile code=font_profile_unsupported detail=hook:BASE14_STYLE_FONTS:missing"


@dataclass
class Result:
    path: Path | None
    untranslated: int = 0


def test_font_worker_subsets_what_the_core_produced(monkeypatch, tmp_path):
    output = tmp_path / "doc-vi.pdf"
    output.write_bytes(PDF)
    core = ModuleType("translate_pdf")
    core.translate_pdf = lambda source, output_dir, **kwargs: Result(output)
    monkeypatch.setitem(sys.modules, "translate_pdf", core)
    subset = []
    monkeypatch.setattr(fonts, "subset_pdf", lambda path: subset.append(path))
    font_worker.wrap_translate_pdf()
    result = core.translate_pdf(tmp_path / "doc.pdf", tmp_path, target_language="vi")
    assert result.path == output and subset == [output]


# ---- Cần PyMuPDF: bỏ qua trong backend/.venv, chạy trong image (lệnh ở Task 8 Step 6) --------------

def make_pdf(path: Path, regular: str, bold: str) -> Path:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quarterly report", fontname=bold, fontsize=18)
    page.insert_textbox(fitz.Rect(72, 100, 540, 400), "Revenue grew by twelve percent while costs stayed flat. " * 6,
                        fontname=regular, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_detect_profile_tells_serif_from_sans(tmp_path):
    assert fonts.detect_profile(make_pdf(tmp_path / "serif.pdf", "tiro", "tibo")) == "serif"
    assert fonts.detect_profile(make_pdf(tmp_path / "sans.pdf", "helv", "hebo")) == "sans"


def test_detect_profile_falls_back_to_sans(tmp_path):
    fitz = pytest.importorskip("fitz")
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4 broken")
    assert fonts.detect_profile(junk) == "sans"
    blank = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(blank)
    doc.close()
    assert fonts.detect_profile(blank) == "sans"  # không có chữ


def test_subset_keeps_the_text_and_shrinks_an_embedded_liberation_font(tmp_path):
    fitz = pytest.importorskip("fitz")
    regular = LIBERATION / "LiberationSans-Regular.ttf"
    if not regular.is_file():
        pytest.skip("cần gói fonts-liberation (có trong image)")
    path = tmp_path / "doc-vi.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="lib", fontfile=str(regular))
    page.insert_text((72, 72), "Tiếng Việt: Đường, Tầng, Nguyễn — dấu chồng ệ ộ ữ", fontname="lib", fontsize=12)
    doc.save(path)
    doc.close()
    before_size = path.stat().st_size
    with fitz.open(path) as check:
        before_text = [p.get_text("text") for p in check]
    lines = []
    assert fonts.subset_pdf(path, lines.append) is True, lines
    assert path.stat().st_size < before_size
    with fitz.open(path) as check:
        assert [p.get_text("text") for p in check] == before_text
