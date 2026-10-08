from __future__ import annotations

import functools
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

MIGRATIONS = Path(__file__).resolve().parent.parent / "alembic"


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Giờ UTC dạng naive — SQLite không lưu múi giờ, nên quy ước mọi cột đều là UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds") + "Z"


@functools.lru_cache(maxsize=4096)
def _fold_vi(text: str) -> str:
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").casefold()


def vi_collation(left: str, right: str) -> int:
    """Thứ tự tên tệp tiếng Việt: bỏ dấu (đ = d) làm khoá chính; bằng nhau thì xét bản gốc casefold, để thứ tự luôn
    xác định. Cố ý không theo thứ tự bảng chữ cái tiếng Việt đầy đủ (a < ă < â): người dùng mong "Ánh" cạnh "An"."""
    for a, b in ((_fold_vi(left), _fold_vi(right)), (unicodedata.normalize("NFC", left).casefold(),
                                                      unicodedata.normalize("NFC", right).casefold())):
        if a != b:
            return -1 if a < b else 1
    return 0


def make_engine(url: str) -> Engine:
    # check_same_thread=False: luồng chạy job ghi DB song song với luồng xử lý request.
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record) -> None:
        dbapi_connection.create_collation("vi", vi_collation)
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def upgrade_db(url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
