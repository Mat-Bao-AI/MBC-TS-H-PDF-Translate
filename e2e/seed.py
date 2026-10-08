"""Chèn N tệp giả (trạng thái lỗi, không có tệp trên đĩa) cho một user — chỉ để thử phân trang."""
import sys
import uuid
from datetime import timedelta

sys.path.insert(0, "/app/backend")

from sqlalchemy import select  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.db import make_engine, make_session_factory, utcnow  # noqa: E402
from app.files.service import normalize_search  # noqa: E402
from app.models import File, User  # noqa: E402

email, count = sys.argv[1], int(sys.argv[2])
factory = make_session_factory(make_engine(load_settings().database_url))
with factory() as db:
    user = db.scalar(select(User).where(User.email == email))
    start = utcnow() - timedelta(days=30)
    for index in range(count):
        name = f"seed {index:02d}.pdf"
        db.add(File(id=uuid.uuid4().hex[:12], user_id=user.id, filename=name, search_name=normalize_search(name),
                    language="vi", status="error", message="seed", created_at=start + timedelta(minutes=index)))
    db.commit()
print(f"seeded {count} for {email}")
