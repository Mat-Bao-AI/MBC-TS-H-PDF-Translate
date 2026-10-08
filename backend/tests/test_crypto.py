import base64

import pytest

from app.providers.crypto import decrypt, encrypt, open_sealed, seal

SECRET = "s" * 32


def test_roundtrip_and_fresh_nonce_each_time():
    first = encrypt(SECRET, "u1", "gemini", "AIza-key")
    second = encrypt(SECRET, "u1", "gemini", "AIza-key")
    assert first != second and "AIza-key" not in first
    assert decrypt(SECRET, "u1", "gemini", first) == "AIza-key" == decrypt(SECRET, "u1", "gemini", second)
    assert len(base64.b64decode(first)) == 12 + len("AIza-key") + 16  # nonce ‖ ciphertext ‖ tag GCM


@pytest.mark.parametrize(("user_id", "provider"), [("u2", "gemini"), ("u1", "google_cloud")])
def test_ciphertext_is_bound_to_user_and_provider(user_id, provider):
    token = encrypt(SECRET, "u1", "gemini", "AIza-key")
    assert decrypt(SECRET, user_id, provider, token) is None


def test_rotated_secret_cannot_decrypt():
    token = encrypt(SECRET, "u1", "gemini", "AIza-key")
    assert decrypt("t" * 32, "u1", "gemini", token) is None


@pytest.mark.parametrize("garbage", ["", "khong-phai-base64!", base64.b64encode(b"ngan").decode()])
def test_garbage_tokens_decrypt_to_none(garbage):
    assert decrypt(SECRET, "u1", "gemini", garbage) is None


def test_seal_and_open_with_a_custom_domain():
    token = seal("k" * 32, "mat-khau-smtp", info=b"instance-settings/v1", aad=b"instance:smtp")
    assert open_sealed("k" * 32, token, info=b"instance-settings/v1", aad=b"instance:smtp") == "mat-khau-smtp"


@pytest.mark.parametrize(("info", "aad"), [
    (b"api-credentials/v1", b"instance:smtp"),      # khác info (khoá dẫn khác)
    (b"instance-settings/v1", b"u1:gemini"),        # khác AAD (bê ciphertext sang chỗ khác)
])
def test_a_token_sealed_for_one_domain_does_not_open_in_another(info, aad):
    token = seal("k" * 32, "mat-khau-smtp", info=b"instance-settings/v1", aad=b"instance:smtp")
    assert open_sealed("k" * 32, token, info=info, aad=aad) is None


def test_api_keys_stored_by_the_old_code_still_decrypt():
    # Token sinh bằng encrypt() TRƯỚC khi tách seal/open_sealed (5ea88b6): định dạng key đã lưu trong DB bị khoá ở đây.
    assert decrypt(SECRET, "u1", "gemini", "QoaR72BIZtUx/cEW052FPLe3jczFPFxSY43Ue+J5BPGY08+sVIxV0g==") == "AIza-old-key"
