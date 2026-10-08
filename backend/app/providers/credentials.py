"""API key + lựa chọn engine mặc định của một người dùng."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import iso, utcnow
from ..engine.fonts import PROFILE_IDS
from ..errors import ApiError
from ..models import ApiCredential, User
from .catalog import DEFAULT_GEMINI_MODEL, ENGINE_BY_ID, PROVIDERS, engine_items, model_choices
from .client import KEY_CHECK_REJECTIONS, ProviderError, Transport, verify_key
from .crypto import decrypt, encrypt

log = logging.getLogger("providers")
KEY_MIN, KEY_MAX = 10, 200


def clean_api_key(raw: str) -> str:
    key = raw.strip()  # dán từ clipboard thường kèm xuống dòng
    # isascii()+isprintable(): chặn luôn zero-width space (U+200B), BOM (U+FEFF) và ký tự ngoài
    # ASCII (vd "ạ", "đ") — isspace() không bắt được các ký tự này, nhưng header HTTP không encode
    # được (UnicodeEncodeError trong http.client) và RequestsTransport chỉ bắt RequestException
    # → 500 nếu lọt xuống đây.
    if (
        not KEY_MIN <= len(key) <= KEY_MAX
        or any(ch.isspace() for ch in key)
        or not (key.isascii() and key.isprintable())
    ):
        raise ApiError(400, "invalid_api_key")
    return key


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ApiError(404, "not_found")


def usable_credentials(db: Session, secret_key: str, user_id: str) -> dict[str, ApiCredential]:
    """Credential của user mà giải mã được bằng SECRET_KEY hiện tại. Đổi SECRET_KEY → dòng cũ bị ẩn,
    người dùng nhập lại là ghi đè (upsert theo user+provider)."""
    rows = db.scalars(select(ApiCredential).where(ApiCredential.user_id == user_id)).all()
    return {row.provider: row for row in rows if decrypt(secret_key, user_id, row.provider, row.secret) is not None}


def load_api_key(db: Session, secret_key: str, user_id: str, provider: str) -> str | None:
    row = db.scalar(select(ApiCredential).where(ApiCredential.user_id == user_id, ApiCredential.provider == provider))
    return None if row is None else decrypt(secret_key, user_id, provider, row.secret)


def _models(credential: ApiCredential | None) -> list[dict] | None:
    if credential is None:
        return None
    try:
        models = json.loads(credential.models)
    except (TypeError, ValueError):  # TypeError: cột NULL (json.loads(None)); ValueError: JSON hỏng
        return []
    if not isinstance(models, list):  # JSON hợp lệ nhưng không phải mảng ("null", "42", "{}", ...)
        return []
    return [m for m in models if isinstance(m, dict) and m.get("id")]


def allowed_models(credential: ApiCredential | None) -> list[dict]:
    return model_choices(_models(credential))


def settings_payload(db: Session, secret_key: str, user: User) -> dict:
    creds = usable_credentials(db, secret_key, user.id)
    return {
        "default_engine": user.default_engine,
        "default_model": user.default_model,
        "default_font": user.default_font,
        "engines": engine_items({provider: provider in creds for provider in PROVIDERS}),
        "gemini_models": allowed_models(creds.get("gemini")),
        "credentials": [
            {"provider": row.provider, "hint": row.hint, "verified_at": iso(row.verified_at), "models": _models(row)}
            for row in creds.values()
        ],
    }


def _pick_model(credential: ApiCredential, wanted: str | None, fallback: str | None) -> str:
    """Model cho gemini: `wanted` (do người dùng chọn) phải nằm trong danh sách; không chọn thì lấy
    `fallback` nếu còn dùng được, rồi model mặc định, rồi model đầu danh sách."""
    ids = [m["id"] for m in allowed_models(credential)]
    if wanted is not None:
        if wanted not in ids:
            raise ApiError(400, "unsupported_model")
        return wanted
    if fallback in ids:
        return fallback
    if DEFAULT_GEMINI_MODEL in ids:
        return DEFAULT_GEMINI_MODEL
    if ids:
        return ids[0]
    # Credential giải mã được nhưng `models` đã lưu là rác (NULL/JSON hỏng) → không có model nào để
    # chọn ngầm định. Cùng mã lỗi với nhánh "wanted không nằm trong ids" ở trên — với người gọi, cả
    # hai đều có nghĩa "không có model nào dùng được cho lựa chọn này" — thay vì ids[0] (IndexError/500).
    raise ApiError(400, "unsupported_model")


def _choose(db: Session, secret_key: str, user: User, engine_id: str, model: str | None, fallback: str | None) -> tuple[str, str | None]:
    engine = ENGINE_BY_ID.get(engine_id)
    if engine is None:
        raise ApiError(400, "unsupported_engine")
    if engine.provider is None:
        return engine.id, None
    creds = usable_credentials(db, secret_key, user.id)
    credential = creds.get(engine.provider)
    if credential is None:
        raise ApiError(400, "missing_api_key")
    if engine.id != "gemini":
        return engine.id, None
    return engine.id, _pick_model(credential, model, fallback)


def set_preferences(db: Session, secret_key: str, user: User, default_engine: str, default_model: str | None,
                    default_font: str | None = None) -> dict:
    """`default_font` None = giữ nguyên font đã lưu (body cũ không có khoá này)."""
    if default_font is not None and default_font not in PROFILE_IDS:
        raise ApiError(400, "unsupported_font")
    engine_id, model = _choose(db, secret_key, user, default_engine, default_model, None)
    user.default_engine, user.default_model = engine_id, model
    if default_font is not None:
        user.default_font = default_font
    db.commit()
    return settings_payload(db, secret_key, user)


def resolve_upload_choice(db: Session, secret_key: str, user: User, engine: str | None, model: str | None) -> tuple[str, str | None]:
    """Engine/model cho một tệp mới: không truyền → mặc định của user (model mặc định nếu còn dùng được)."""
    return _choose(db, secret_key, user, engine or user.default_engine, model, user.default_model)


def _find_credential(db: Session, user_id: str, provider: str) -> ApiCredential | None:
    return db.scalar(select(ApiCredential).where(ApiCredential.user_id == user_id, ApiCredential.provider == provider))


def save_credential(db: Session, secret_key: str, user: User, provider: str, api_key: str, transport: Transport) -> dict:
    _check_provider(provider)
    key = clean_api_key(api_key)
    try:
        models = verify_key(provider, key, transport)  # gọi nhà cung cấp TRƯỚC, hỏng thì không lưu gì
    except ProviderError as error:
        # Một dòng chẩn đoán (mã của Google, không thân lỗi, không key) để biết vì sao key bị từ chối.
        log.warning("Kiểm key thất bại: %s", error.diagnostic(provider, secret=key))
        if error.code in KEY_CHECK_REJECTIONS:  # key sai, API chưa bật, chưa bật thanh toán, key bị giới hạn…
            raise ApiError(400, error.code) from None
        raise ApiError(502, "provider_unavailable") from None  # mạng, 5xx, giới hạn tốc độ/hạn mức lúc kiểm
    # Quyết định của controller (ghi đè brief): key verify OK nhưng danh sách model dùng được rỗng
    # (toàn model bị loại bởi EXCLUDED_MODEL_WORDS hoặc không có generateContent) → từ chối trước khi
    # đụng tới DB thay vì để `ids[0]` ở dưới ném IndexError (500) khi first_time + google_free.
    if provider == "gemini" and not model_choices(models):
        raise ApiError(400, "no_usable_models")
    now = utcnow()

    def _apply(target: ApiCredential, first_time: bool) -> None:
        target.secret = encrypt(secret_key, user.id, provider, key)
        target.hint = key[-4:]
        target.models = json.dumps(models, ensure_ascii=False)
        target.verified_at = target.updated_at = now
        if provider == "gemini" and first_time and user.default_engine == "google_free":
            ids = [m["id"] for m in model_choices(models)]
            user.default_engine = "gemini"
            user.default_model = DEFAULT_GEMINI_MODEL if DEFAULT_GEMINI_MODEL in ids else ids[0]

    row = _find_credential(db, user.id, provider)
    if row is None:
        new_row = ApiCredential(id=uuid.uuid4().hex[:12], user_id=user.id, provider=provider, created_at=now)
        _apply(new_row, first_time=True)  # dòng mới tinh: chắc chắn là lần đầu
        db.add(new_row)
        try:
            db.flush()
        except IntegrityError:
            # Race trên UNIQUE(user_id, provider): một request khác vừa insert xong dòng này ngay
            # trước ta (lookup ở trên không thấy kịp). rollback huỷ cả new_row lẫn thay đổi
            # default_engine/default_model vừa gán (chưa commit) — đọc lại dòng THẬT rồi áp lại
            # đúng một lần, với first_time tính từ secret CŨ của chính dòng đó.
            db.rollback()
            row = _find_credential(db, user.id, provider)
            assert row is not None
            _apply(row, first_time=decrypt(secret_key, user.id, provider, row.secret) is None)
    else:
        # Dòng cũ tồn tại nhưng không giải mã được nữa (đổi SECRET_KEY) bị ẩn khỏi mọi nơi khác như
        # chưa từng có key — lưu lại phải tính là lần đầu, không phải chỉ dựa vào "có dòng DB hay
        # không". Đọc secret CŨ trước khi `_apply` ghi đè nó.
        _apply(row, first_time=decrypt(secret_key, user.id, provider, row.secret) is None)
    db.commit()
    return settings_payload(db, secret_key, user)


def drop_gemini_model(db: Session, user_id: str, model: str) -> str | None:
    """§3: model bị Google gỡ (job lỗi `model_unavailable`) → bỏ khỏi danh sách model của credential gemini của chủ
    tệp. Nếu đó là model mặc định: về DEFAULT_GEMINI_MODEL nếu key còn dùng được, không thì model đầu tiên còn lại
    của ô chọn; hết model → Google miễn phí. Trả nhãn ngắn của mặc định mới khi mặc định vừa đổi, None nếu không đổi.
    Lưu lại key (PUT credentials) nạp lại danh sách từ Google — model còn sống thì quay lại."""
    credential = _find_credential(db, user_id, "gemini")
    user = db.get(User, user_id)
    if credential is None or user is None:
        return None
    remaining = [item for item in (_models(credential) or []) if item.get("id") != model]
    credential.models = json.dumps(remaining, ensure_ascii=False)
    label: str | None = None
    if user.default_engine == "gemini" and user.default_model == model:
        choices = model_choices(remaining)
        if not choices:
            user.default_engine, user.default_model = "google_free", None
            label = ENGINE_BY_ID["google_free"].label
        else:
            ids = [choice["id"] for choice in choices]
            user.default_model = DEFAULT_GEMINI_MODEL if DEFAULT_GEMINI_MODEL in ids else ids[0]
            label = next(c["label"] for c in choices if c["id"] == user.default_model).split(" — ")[0]
    db.commit()
    return label


def delete_credential(db: Session, user: User, provider: str) -> None:
    _check_provider(provider)
    db.execute(delete(ApiCredential).where(ApiCredential.user_id == user.id, ApiCredential.provider == provider))
    default = ENGINE_BY_ID.get(user.default_engine)
    if default is not None and default.provider == provider:
        user.default_engine, user.default_model = "google_free", None
    db.commit()
