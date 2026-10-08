from __future__ import annotations

import re
from pathlib import Path


def file_dir(users_dir: Path, user_id: str, file_id: str) -> Path:
    return users_dir / user_id / file_id


def safe_name(filename: str) -> str:
    """Giữ tên gốc nhưng bỏ mọi ký tự có thể thoát ra khỏi thư mục tệp.

    Nhân đặt tên đầu ra là "<tên gốc>-<mã ngôn ngữ>.pdf", nên phải lưu theo tên gốc
    đã làm sạch — lưu thành "input.pdf" thì người dùng tải về "input-vi.pdf".
    """
    stem = Path(filename).stem[:80]
    stem = re.sub(r"[^\w.\- ]", "_", stem, flags=re.UNICODE).strip() or "tailieu"
    return stem + ".pdf"
