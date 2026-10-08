import re

from app.security import hash_password, new_token, token_hash, verify_password


def test_hash_and_verify_roundtrip():
    hashed = hash_password("correct horse")
    assert hashed != "correct horse"
    assert verify_password(hashed, "correct horse")
    assert not verify_password(hashed, "wrong horse")


def test_missing_or_garbage_hash_never_verifies():
    assert verify_password(None, "anything") is False
    assert verify_password("not-a-hash", "anything") is False


def test_token_hash_depends_on_secret():
    assert token_hash("a" * 32, "t") != token_hash("b" * 32, "t")
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash("a" * 32, "t"))


def test_new_token_is_random_and_urlsafe():
    first, second = new_token(), new_token()
    assert first != second
    assert re.fullmatch(r"[\w-]{43}", first)
