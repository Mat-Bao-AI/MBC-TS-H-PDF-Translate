from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# So với một hash giả khi email không tồn tại: thời gian phản hồi không lộ email nào có tài khoản.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError, UnicodeEncodeError):
        # UnicodeEncodeError: surrogate lẻ — không mã hoá được UTF-8 thì không thể là mật khẩu đã lưu.
        return False
    return password_hash is not None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(secret_key: str, token: str) -> str:
    # "surrogatepass": token gõ tay có surrogate lẻ (JSON cho phép "\ud800") vẫn băm được thay vì 500. Dãy byte đó
    # không phải UTF-8 hợp lệ nên không trùng mã hoá của token thật nào → tra không thấy → invalid_token như thường.
    # Chuỗi bình thường mã hoá y hệt trước: hash của token / phiên đang có không đổi.
    return hmac.new(secret_key.encode(), token.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()
