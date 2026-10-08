"""Sinh e2e/fixtures/sample-2p.pdf: PDF tổng hợp 2 trang (tiêu đề + tiêu đề mục + vài đoạn tiếng Anh).

Không dùng phông ngoài (chỉ phông Helvetica/Times dựng sẵn của PDF), không ngẫu nhiên: chạy lại ra đúng tệp cũ.
PyMuPDF không có trong backend/.venv; sinh bên trong image (không cần mạng):

    docker run --rm --network none -v "$PWD/e2e/fixtures:/f" --entrypoint python \
        vi-translate-saas:local /f/make_sample_pdf.py /f/sample-2p.pdf
"""
import sys

import fitz  # PyMuPDF

PAGES = [
    {
        "title": "A Short Guide to Reading Maps",
        "heading": "1. Scales and symbols",
        "paragraphs": [
            "A map is a flat picture of a place. The scale tells you how a distance on the paper "
            "relates to the real distance on the ground. For example, a scale of one to fifty thousand "
            "means that one centimetre on the map stands for half a kilometre in the world.",
            "Symbols save space. A small blue line usually shows a river, a green patch shows a forest, "
            "and a thin black line shows a road. The legend, often printed in a corner of the sheet, "
            "explains every symbol that the mapmaker used.",
            "Before a long walk, check the scale first. Measure the route with a piece of string, "
            "then compare the string against the scale bar to estimate how far you will travel.",
        ],
    },
    {
        "title": "A Short Guide to Reading Maps",
        "heading": "2. Directions and contour lines",
        "paragraphs": [
            "Most maps are drawn with north at the top. A small arrow near the edge confirms the "
            "direction, and a compass helps you line the map up with the land around you.",
            "Contour lines connect points of equal height. When the lines sit close together the slope "
            "is steep, and when they are far apart the ground is almost flat. A set of closed circles "
            "usually marks the top of a hill.",
            "With practice you can read a map the way you read a page of text: scan the legend, find "
            "your position, pick a landmark, and follow the lines to the place you want to reach.",
        ],
    },
]

MARGIN = 72
TITLE_SIZE, HEADING_SIZE, BODY_SIZE = 20, 14, 11


def build(path: str) -> None:
    doc = fitz.open()
    for page_def in PAGES:
        page = doc.new_page(width=595, height=842)  # A4
        width = page.rect.width - 2 * MARGIN
        y = MARGIN
        page.insert_text((MARGIN, y + TITLE_SIZE), page_def["title"], fontname="hebo", fontsize=TITLE_SIZE)
        y += TITLE_SIZE + 36
        page.insert_text((MARGIN, y + HEADING_SIZE), page_def["heading"], fontname="hebo", fontsize=HEADING_SIZE)
        y += HEADING_SIZE + 18
        for text in page_def["paragraphs"]:
            rect = fitz.Rect(MARGIN, y, MARGIN + width, y + 140)
            leftover = page.insert_textbox(rect, text, fontname="helv", fontsize=BODY_SIZE, lineheight=1.4)
            if leftover < 0:
                raise SystemExit("đoạn văn không vừa khung")
            lines = int(-(-fitz.get_text_length(text, fontname="helv", fontsize=BODY_SIZE) // width))
            y += lines * BODY_SIZE * 1.4 + 14
    # Siêu dữ liệu cố định: không ngày giờ hiện tại, để kết quả lặp lại được.
    doc.set_metadata({
        "title": "Sample document for tests", "author": "", "subject": "", "keywords": "",
        "creator": "make_sample_pdf.py", "producer": "PyMuPDF",
        "creationDate": "D:20260101000000Z", "modDate": "D:20260101000000Z",
    })
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
    doc.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("dùng: make_sample_pdf.py <tệp-đầu-ra.pdf>")
    build(sys.argv[1])
