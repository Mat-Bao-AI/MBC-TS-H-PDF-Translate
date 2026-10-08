"""Mã hoá bí mật để lưu DB: API key của người dùng (encrypt/decrypt), mật khẩu SMTP (seal/open_sealed, system/store.py).

AES-GCM với khoá dẫn từ SECRET_KEY (HKDF-SHA256, mỗi loại bí mật một `info`) — đổi SECRET_KEY là mọi key
không giải mã được nữa và app coi như người dùng chưa nhập key (xem DEPLOY.md). Associated data
"<user_id>:<provider>" chặn việc bê ciphertext của người này/provider này sang chỗ khác trong DB.
"""

from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

INFO = b"api-credentials/v1"
NONCE_BYTES = 12


@lru_cache(maxsize=8)
def _derive(secret_key: str, info: bytes = INFO) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret_key.encode("utf-8"))


def _aad(user_id: str, provider: str) -> bytes:
    return f"{user_id}:{provider}".encode("utf-8")


def seal(secret_key: str, plaintext: str, *, info: bytes = INFO, aad: bytes) -> str:
    """AES-GCM với khoá dẫn theo `info` và associated data `aad` — mỗi loại bí mật một miền riêng."""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_derive(secret_key, info)).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def open_sealed(secret_key: str, token: str, *, info: bytes = INFO, aad: bytes) -> str | None:
    """None khi token hỏng, sai miền (info/aad), hoặc SECRET_KEY đã đổi — người gọi coi như không có bí mật."""
    try:
        raw = base64.b64decode(token, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) <= NONCE_BYTES:
        return None
    try:
        plain = AESGCM(_derive(secret_key, info)).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], aad)
    except InvalidTag:
        return None
    return plain.decode("utf-8", errors="replace")


def encrypt(secret_key: str, user_id: str, provider: str, plaintext: str) -> str:
    return seal(secret_key, plaintext, aad=_aad(user_id, provider))


def decrypt(secret_key: str, user_id: str, provider: str, token: str) -> str | None:
    return open_sealed(secret_key, token, aad=_aad(user_id, provider))
