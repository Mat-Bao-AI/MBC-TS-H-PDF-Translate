import errno
import json
import unicodedata
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, func, select, update

from app.db import utcnow
from app.engine.paths import file_dir
from app.files import service
from app.models import File, FileVersion, User
from app.system.store import instance_row
from helpers import PDF, save_key, upload, wait_file


@pytest.fixture
def me(sign_up) -> dict:
    return sign_up("an@example.com")


def seed(client, user_id, names, status="done") -> None:
    """Chèn thẳng vào DB — nhanh hơn upload thật khi chỉ cần kiểm danh sách."""
    start = utcnow() - timedelta(hours=1)
    with client.app.state.session_factory() as db:
        for index, name in enumerate(names):
            db.add(File(id=f"seed{index:08d}", user_id=user_id, filename=name,
                        search_name=service.normalize_search(name), language="vi", status=status,
                        created_at=start + timedelta(seconds=index)))
        db.commit()


def names(client, q) -> list[str]:
    return sorted(item["filename"] for item in client.get("/api/files", params={"q": q}).json()["items"])


def test_upload_translates_and_lists_the_file(client, me):
    response = upload(client, "Báo cáo.pdf")
    assert response.status_code == 202
    item = response.json()
    assert item["filename"] == "Báo cáo.pdf" and item["status"] == "queued"
    assert item["created_at"].endswith("Z")
    done = wait_file(client, item["id"])
    assert done["status"] == "done" and done["finished_at"].endswith("Z")
    listing = client.get("/api/files").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == item["id"]


def test_files_require_login(client):
    assert client.get("/api/files").status_code == 401
    assert upload(client).status_code == 401


@pytest.mark.parametrize(("name", "data", "language", "code"), [
    ("doc.pdf", b"not a pdf at all", "vi", "not_pdf"),
    ("doc.docx", PDF, "vi", "not_pdf"),
    ("doc.pdf", PDF, "zh", "unsupported_language"),
])
def test_upload_rejects_bad_input(client, me, name, data, language, code):
    response = upload(client, name, data, language)
    assert response.status_code == 400 and response.json() == {"detail": {"code": code}}
    assert client.get("/api/files").json()["total"] == 0


def test_upload_size_limit_cleans_up(client, me, settings):
    client.app.state.settings = replace(client.app.state.settings, max_upload_mb=1)
    response = upload(client, "big.pdf", PDF + b"0" * (1024 * 1024))
    assert response.status_code == 413 and response.json() == {"detail": {"code": "too_large", "mb": 1}}
    assert list(settings.users_dir.rglob("*.pdf")) == []


def test_pending_limit_per_user(client, me):
    for index in range(3):
        assert upload(client, f"slow-{index}.pdf").status_code == 202
    response = upload(client, "them-mot.pdf")
    assert response.status_code == 429
    assert response.json() == {"detail": {"code": "too_many_pending", "limit": 3}}


def test_pending_limit_follows_the_instance_setting_and_falls_back_to_env(client, me):
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = 1
        db.commit()
    assert upload(client, "slow-0.pdf").status_code == 202
    response = upload(client, "them.pdf")
    assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_pending", "limit": 1}}
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = None  # NULL = theo env (3), có hiệu lực ngay, không khởi động lại
        db.commit()
    assert upload(client, "them.pdf").status_code == 202
    assert upload(client, "them-nua.pdf").status_code == 202
    assert upload(client, "qua-han.pdf").json() == {"detail": {"code": "too_many_pending", "limit": 3}}


def retranslate(client, file_id, language="vi", engine="google_free", model=None, font="auto"):
    return client.post(f"/api/files/{file_id}/retranslate", json={"language": language, "engine": engine, "model": model, "font": font})


def test_retranslate_a_done_file_keeps_the_old_translation_until_the_new_one_is_ready(client, me):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    old = client.get(f"/api/files/{file_id}/download").content
    blocker = upload(client, "slow.pdf").json()["id"]  # worker giả ngủ 3 s: lượt dịch lại xếp hàng sau nó
    wait_file(client, blocker, statuses=("running",))
    response = retranslate(client, file_id, language="en", font="serif")
    assert response.status_code == 202
    item = response.json()
    assert (item["status"], item["retranslating"], item["rebuilding"], item["rebuild_font"]) == ("queued", True, False, "serif")
    assert item["retranslate_to"] == {"language": "en", "engine": "google_free", "model": None, "font": "serif"}
    assert (item["language"], item["font"], item["done_pages"], item["rebuild_error"]) == ("vi", "auto", 0, "")  # bản cũ vẫn là bản chính
    during = client.get(f"/api/files/{file_id}/download")
    assert during.status_code == 200 and during.content == old and "doc-vi.pdf" in during.headers["content-disposition"]
    done = wait_file(client, file_id)
    assert (done["status"], done["language"], done["font"], done["retranslating"], done["retranslate_to"], done["rebuild_font"]) == (
        "done", "en", "serif", False, None, None)
    after = client.get(f"/api/files/{file_id}/download")
    assert after.content.endswith(b"% rebuilt font=serif\n") and "doc-en.pdf" in after.headers["content-disposition"]
    wait_file(client, blocker)


def test_retranslate_a_failed_file_requeues_it_in_place_with_the_new_choice(client, me):
    file_id = upload(client, "fail.pdf").json()["id"]
    failed = wait_file(client, file_id)
    response = retranslate(client, file_id, language="en", font="sans")
    assert response.status_code == 202
    item = response.json()
    assert (item["status"], item["message"], item["language"], item["font"], item["retranslating"], item["rebuilding"]) == (
        "queued", "", "en", "sans", False, False)
    again = wait_file(client, file_id)
    assert again["status"] == "error" and again["finished_at"] >= failed["finished_at"] and again["language"] == "en"


def test_retranslate_a_failed_file_leaves_the_segment_table_to_the_worker(client, me, settings):
    """Bảng đã dịch (đã trả tiền) + meta không bị service đụng — worker handoff tự quyết theo meta (khớp thì dùng lại, lệch thì bỏ)."""
    file_id = upload(client, "fail.pdf").json()["id"]
    wait_file(client, file_id)
    directory = file_dir(settings.users_dir, me["id"], file_id)
    (directory / "segments.jsonl").write_text('{"src": "a", "dst": "b"}\n', encoding="utf-8")
    (directory / "segments.meta.json").write_text("{}", encoding="utf-8")
    assert retranslate(client, file_id, language="en").status_code == 202  # đổi ngôn ngữ: service vẫn không xoá bảng
    wait_file(client, file_id)
    assert (directory / "segments.jsonl").read_text(encoding="utf-8") == '{"src": "a", "dst": "b"}\n'
    assert (directory / "segments.meta.json").is_file()


def test_retranslate_a_failed_file_removes_its_stale_output_single_and_bulk(client, me, settings):
    ids = seed_rows(client, me["id"], [("don.pdf", "error", 0), ("loat.pdf", "error", 1)])
    client.app.state.runner.stop()  # chỉ kiểm phần service: tệp nằm lại hàng đợi
    for file_id, name in zip(ids, ("don-vi.pdf", "loat-vi.pdf")):
        (file_dir(settings.users_dir, me["id"], file_id) / name).write_bytes(PDF)
    with client.app.state.session_factory() as db:
        db.execute(update(File).where(File.id == ids[0]).values(output_name="don-vi.pdf"))
        db.execute(update(File).where(File.id == ids[1]).values(output_name="loat-vi.pdf"))
        db.commit()
    assert retranslate(client, ids[0], language="en").json()["status"] == "queued"
    assert bulk_retranslate(client, {"ids": [ids[1]]}).json()["queued"] == 1
    for file_id, name in zip(ids, ("don-vi.pdf", "loat-vi.pdf")):
        assert not (file_dir(settings.users_dir, me["id"], file_id) / name).exists()
    with client.app.state.session_factory() as db:
        assert [db.get(File, file_id).output_name for file_id in ids] == [None, None]


def test_retranslate_only_done_or_failed_files_and_retry_is_gone(client, me):
    pending = upload(client, "slow.pdf").json()["id"]
    response = retranslate(client, pending)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "not_retranslatable"}}
    wait_file(client, pending, statuses=("running",))
    assert retranslate(client, pending).status_code == 409
    assert client.post(f"/api/files/{pending}/retry").status_code == 404
    wait_file(client, pending)


@pytest.mark.parametrize(("body", "code"), [
    ({"language": "zh"}, "unsupported_language"), ({"engine": "deepl"}, "unsupported_engine"), ({"font": "comic"}, "unsupported_font"),
    ({"engine": "gemini"}, "missing_api_key"), ({"engine": "google_cloud"}, "missing_api_key"),
])
def test_retranslate_validates_the_choice_before_touching_the_file(client, me, body, code):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    response = retranslate(client, file_id, **body)
    assert response.status_code == 400 and response.json() == {"detail": {"code": code}}
    item = client.get(f"/api/files/{file_id}").json()
    assert (item["status"], item["retranslating"]) == ("done", False)


def test_retranslate_with_gemini_checks_the_model_against_the_key(client, me):
    save_key(client, "gemini")
    file_id = upload(client, "doc.pdf", engine="google_free").json()["id"]
    wait_file(client, file_id)
    response = retranslate(client, file_id, engine="gemini", model="gemini-3.0-flash")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "unsupported_model"}}
    item = retranslate(client, file_id, engine="gemini").json()  # model null → model mặc định của key
    assert item["retranslate_to"] == {"language": "vi", "engine": "gemini", "model": "gemini-3.5-flash-lite", "font": "auto"}
    assert wait_file(client, file_id)["engine"] == "gemini"


def test_retranslate_takes_a_pending_slot_with_the_effective_limit(client, me):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = 1
        db.commit()
    blocker = upload(client, "slow.pdf").json()["id"]
    response = retranslate(client, file_id)
    assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_pending", "limit": 1}}
    assert client.get(f"/api/files/{file_id}").json()["status"] == "done"
    wait_file(client, blocker)


# ---- Chế độ nâng cao: snapshot (spec 2026-10-14 §3, §7) --------------------------------------------------------


def enable_advanced(client, default_profile=None):
    """Bật Chế độ nâng cao như UI thật: động cơ mặc định là AI (spec 2026-10-15 §6 — động cơ thuần làm server tắt chế độ). Mọi test
    gọi hàm này đều đã save_key(client, "gemini") trước."""
    body = {"default_engine": "gemini", "default_model": "gemini-3.5-flash-lite", "advance_mode": True, "default_profile": default_profile}
    response = client.put("/api/settings/preferences", json=body)
    assert response.status_code == 200 and response.json()["advance_mode"] is True, response.text


def upload_advanced(client, name="doc.pdf", *, engine="gemini", model=None, profile=None, style=None, context=None, language="vi"):
    form = {"language": language, "engine": engine}
    if model:
        form["model"] = model
    if profile is not None:
        form["profile"] = profile
    if style is not None:
        form["style"] = style if isinstance(style, str) else json.dumps(style)
    if context is not None:
        form["context"] = context
    return client.post("/api/files", files={"file": (name, PDF, "application/pdf")}, data=form)


def retranslate_advanced(client, file_id, *, engine="gemini", **extra):
    return client.post(f"/api/files/{file_id}/retranslate", json={"language": "vi", "engine": engine, "model": None, "font": "auto", **extra})


TECHNICAL_STYLE = {"fidelity": "balanced", "tone": "professional", "audience": "expert", "terms": "keep", "proper_names": "keep",
                   "numbers": "keep", "dates": "keep", "abbreviations": "keep",
                   "custom_instructions": "Giữ nguyên tên thư viện, hàm, lệnh, tham số, tệp và mọi định danh trong mã."}


def test_upload_with_a_profile_stores_a_value_snapshot_with_overrides(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    technical = next(item for item in client.get("/api/profiles").json() if item["preset_slug"] == "technical")  # đã gieo: preset: → dòng của tôi
    response = upload_advanced(client, profile="preset:technical", style={"tone": "friendly", "terms": "keep"}, context="Tài liệu API nội bộ.")
    assert response.status_code == 202
    item = response.json()
    assert item["version_no"] == 1
    assert item["config"] == {
        "schema": 1, "mode": "advanced", "profile": {"id": technical["id"], "name": "Tài liệu kỹ thuật", "kind": "custom"},
        "style": {**TECHNICAL_STYLE, "tone": "friendly"}, "overrides": ["tone"],  # terms=keep trùng hồ sơ → không phải ghi đè
        "document_context": "Tài liệu API nội bộ."}
    assert wait_file(client, item["id"])["config"] == item["config"]


def test_upload_without_any_advanced_field_has_no_snapshot_even_in_advance_mode(client, me):
    save_key(client, "gemini")
    enable_advanced(client, default_profile="preset:quick")  # hồ sơ mặc định chỉ là gợi ý cho UI: server không tự áp
    assert upload_advanced(client).json()["config"] is None
    assert upload_advanced(client, style={}, context="").json()["config"] is None
    assert upload(client, "thuan.pdf").json()["config"] is None


def test_style_without_a_profile_keeps_only_the_sent_fields(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    config = upload_advanced(client, style={"tone": "simple"}).json()["config"]
    assert (config["profile"], config["style"], config["overrides"], config["document_context"]) == (None, {"tone": "simple"}, ["tone"], None)


def test_advanced_fields_are_refused_when_the_mode_is_off_or_the_engine_is_not_ai(client, me):
    save_key(client, "gemini")
    response = upload_advanced(client, profile="preset:quick")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "advance_mode_off"}}
    enable_advanced(client)
    response = upload_advanced(client, engine="google_free", context="x")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "style_requires_ai"}}
    assert client.get("/api/files").json()["total"] == 0  # kiểm trước khi ghi đĩa / xếp hàng
    assert list(client.app.state.settings.users_dir.rglob("*.pdf")) == []


def test_advanced_fields_are_refused_with_google_cloud_too(client, me):
    """Cloud Translation v2 là dịch máy thuần (không nhận prompt) dù có key: cùng `style_requires_ai` như Google miễn phí."""
    save_key(client, "gemini")  # chỉ để bật được chế độ (mặc định phải là AI); test này gửi engine google_cloud
    save_key(client, "google_cloud")
    enable_advanced(client)
    extras = ({"profile": "preset:quick"}, {"style": {"tone": "simple"}}, {"context": "x"})
    for extra in extras:
        response = upload_advanced(client, engine="google_cloud", **extra)
        assert response.status_code == 400 and response.json() == {"detail": {"code": "style_requires_ai"}}
    assert client.get("/api/files").json()["total"] == 0
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    for extra in extras:
        response = retranslate_advanced(client, file_id, engine="google_cloud", **extra)
        assert response.status_code == 400 and response.json() == {"detail": {"code": "style_requires_ai"}}
    item = client.get(f"/api/files/{file_id}").json()
    assert (item["status"], item["retranslating"], item["config"]) == ("done", False, None)


def test_advanced_fields_are_checked_before_the_pending_limit_and_before_any_write(client, me, settings):
    save_key(client, "gemini")
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = 1
        db.commit()
    blocker = upload(client, "slow.pdf").json()["id"]
    assert upload(client, "them.pdf").json() == {"detail": {"code": "too_many_pending", "limit": 1}}  # đã chạm hạn chờ
    assert retranslate_advanced(client, file_id).json() == {"detail": {"code": "too_many_pending", "limit": 1}}
    for response in (upload_advanced(client, context="x"), retranslate_advanced(client, file_id, profile="preset:quick")):
        assert response.status_code == 400 and response.json() == {"detail": {"code": "advance_mode_off"}}
    enable_advanced(client)
    for response in (upload_advanced(client, style={"tone": "shouty"}), retranslate_advanced(client, file_id, style={"tone": "shouty"})):
        assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_style", "field": "tone"}}
    assert client.get("/api/files").json()["total"] == 2
    assert sorted(path.name for path in (settings.users_dir / me["id"]).iterdir()) == sorted([file_id, blocker])  # không thư mục job mới
    item = client.get(f"/api/files/{file_id}").json()
    assert (item["status"], item["retranslating"], item["config"]) == ("done", False, None)
    wait_file(client, blocker)


@pytest.mark.parametrize(("kwargs", "status", "detail"), [
    ({"profile": "preset:nope"}, 400, {"code": "profile_not_found"}),
    ({"profile": "khac00000000"}, 400, {"code": "profile_not_found"}),
    ({"style": "not json"}, 422, {"code": "invalid_style", "field": "style"}),
    ({"style": "[1]"}, 422, {"code": "invalid_style", "field": "style"}),
    ({"style": {"tone": "shouty"}}, 422, {"code": "invalid_style", "field": "tone"}),
    ({"style": {"glossary": {}}}, 422, {"code": "invalid_style", "field": "glossary"}),
    ({"style": {"custom_instructions": "x" * 1001}}, 422, {"code": "invalid_style", "field": "custom_instructions"}),
    ({"context": "y" * 2001}, 422, {"code": "invalid_style", "field": "context"}),
    ({"context": "a\x07b"}, 422, {"code": "invalid_style", "field": "context"}),
    ({"style": "[" * 100_000 + "]" * 100_000}, 422, {"code": "invalid_style", "field": "style"}),  # RecursionError, không 500
])
def test_bad_advanced_fields_are_refused_with_the_field(client, me, kwargs, status, detail):
    save_key(client, "gemini")
    enable_advanced(client)
    response = upload_advanced(client, **kwargs)
    assert response.status_code == status and response.json() == {"detail": detail}
    assert client.get("/api/files").json()["total"] == 0


def test_an_empty_style_counts_as_not_sent_even_with_the_mode_off(client, me):
    """Client khác gửi `style: {}` khi Chế độ nâng cao tắt: không có gì nâng cao → tệp cơ bản (config NULL), không 400."""
    save_key(client, "gemini")
    response = upload_advanced(client, style={})
    assert response.status_code == 202 and response.json()["config"] is None
    file_id = response.json()["id"]
    wait_file(client, file_id)
    response = retranslate_advanced(client, file_id, style={})
    assert response.status_code == 202 and response.json()["config"] is None
    assert wait_file(client, file_id)["config"] is None


def test_another_users_profile_is_not_found_for_the_default_or_an_upload(client, sign_up):
    sign_up("an@example.com")
    theirs = client.post("/api/profiles", json={"name": "Của An", "tone": "friendly"}).json()["id"]
    sign_up("binh@example.com")
    save_key(client, "gemini")
    body = {"default_engine": "google_free", "advance_mode": True, "default_profile": theirs}
    response = client.put("/api/settings/preferences", json=body)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "profile_not_found"}}
    enable_advanced(client)
    response = upload_advanced(client, profile=theirs)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "profile_not_found"}}
    assert client.get("/api/files").json()["total"] == 0


def test_a_snapshot_survives_deleting_its_profile(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    mine = client.post("/api/profiles", json={"name": "Riêng", "tone": "friendly"}).json()["id"]
    item = upload_advanced(client, profile=mine).json()
    assert client.delete(f"/api/profiles/{mine}").status_code == 204
    again = client.get(f"/api/files/{item['id']}").json()
    assert again["config"]["profile"] == {"id": mine, "name": "Riêng", "kind": "custom"} and again["config"]["style"]["tone"] == "friendly"
    response = upload_advanced(client, profile=mine)
    assert response.status_code == 400 and response.json() == {"detail": {"code": "profile_not_found"}}


def test_retranslate_a_done_file_parks_the_new_snapshot_until_the_new_translation_is_ready(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    rows = {item["preset_slug"]: item["id"] for item in client.get("/api/profiles").json()}
    file_id = upload_advanced(client, profile="preset:quick").json()["id"]
    wait_file(client, file_id)
    blocker = upload(client, "slow.pdf").json()["id"]  # worker giả ngủ 3 s: lượt dịch lại xếp hàng sau nó
    wait_file(client, blocker, statuses=("running",))
    item = retranslate_advanced(client, file_id, profile="preset:academic", context="Luận văn.").json()
    assert item["status"] == "queued" and item["config"]["profile"]["id"] == rows["quick"]  # bản chính vẫn mang snapshot cũ
    with client.app.state.session_factory() as db:
        parked = json.loads(db.get(File, file_id).retranslate_config)
    assert parked["profile"]["id"] == rows["academic"] and parked["document_context"] == "Luận văn."
    done = wait_file(client, file_id)
    assert done["config"]["profile"]["id"] == rows["academic"] and done["config"]["document_context"] == "Luận văn."
    with client.app.state.session_factory() as db:
        assert db.get(File, file_id).retranslate_config is None
    wait_file(client, blocker)


def test_a_failed_retranslate_drops_the_parked_snapshot_and_keeps_the_current_one(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    file_id = upload_advanced(client, "rebuildfail.pdf", context="Cũ").json()["id"]
    wait_file(client, file_id)
    assert retranslate_advanced(client, file_id, context="Mới").status_code == 202
    item = wait_file(client, file_id)
    assert item["status"] == "done" and item["rebuild_error"] and item["config"]["document_context"] == "Cũ"
    with client.app.state.session_factory() as db:
        assert db.get(File, file_id).retranslate_config is None


def test_retranslate_a_failed_file_writes_the_new_snapshot_in_place(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    file_id = upload_advanced(client, "fail.pdf", context="Cũ").json()["id"]
    wait_file(client, file_id)
    item = retranslate_advanced(client, file_id, context="Mới").json()
    assert item["status"] == "queued" and item["config"]["document_context"] == "Mới"
    assert wait_file(client, file_id)["config"]["document_context"] == "Mới"  # lại lỗi (worker giả): snapshot vẫn của lượt vừa yêu cầu
    assert retranslate_advanced(client, file_id).json()["config"] is None  # không gửi gì → về cơ bản


def test_retranslate_refuses_advanced_fields_like_upload(client, me):
    save_key(client, "gemini")
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    assert retranslate_advanced(client, file_id, context="x").json() == {"detail": {"code": "advance_mode_off"}}
    enable_advanced(client)
    assert retranslate_advanced(client, file_id, engine="google_free", profile="preset:quick").json() == {"detail": {"code": "style_requires_ai"}}
    response = retranslate_advanced(client, file_id, style={"numbers": "roman"})
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_style", "field": "numbers"}}
    assert client.get(f"/api/files/{file_id}").json()["status"] == "done"


def test_bulk_retranslate_keeps_each_files_snapshot_only_for_ai_engines(client, me):
    save_key(client, "gemini")
    enable_advanced(client)
    ids = seed_rows(client, me["id"], [("done-ai.pdf", "done", 0), ("error-ai.pdf", "error", 1), ("done-plain.pdf", "done", 2)])
    client.app.state.runner.stop()  # chỉ kiểm phần service: tệp nằm lại hàng đợi
    snap = json.dumps({"schema": 1, "mode": "advanced", "profile": None, "style": None, "overrides": [], "document_context": "Ngữ cảnh"})

    def reset():
        with client.app.state.session_factory() as db:
            db.execute(update(File).where(File.id == ids[0]).values(status="done"))
            db.execute(update(File).where(File.id == ids[1]).values(status="error"))
            db.execute(update(File).where(File.id == ids[2]).values(status="done"))
            db.execute(update(File).where(File.id.in_(ids)).values(retranslate_language=None, retranslate_engine=None,
                                                                   retranslate_model=None, rebuild_font=None, retranslate_config=None))
            db.execute(update(File).where(File.id.in_(ids[:2])).values(engine="gemini", model="gemini-3.5-flash-lite", config=snap))
            db.commit()

    def parked():
        with client.app.state.session_factory() as db:
            return [(db.get(File, file_id).config, db.get(File, file_id).retranslate_config) for file_id in ids]

    # Giữ cài đặt riêng: tệp AI giữ snapshot của chính nó (done → đỗ ở retranslate_config, error → giữ config); tệp thuần không có gì.
    reset()
    assert bulk_retranslate(client, {"ids": ids, "settings": None}).json()["queued"] == 3
    assert parked() == [(snap, snap), (snap, None), (None, None)]
    # Áp một cài đặt với động cơ THUẦN: lượt này chạy cơ bản — snapshot của lượt = NULL; bản hiện tại vẫn mang config tới khi bị thay.
    reset()
    plain = {"language": "vi", "engine": "google_free", "model": None, "font": "auto"}
    assert bulk_retranslate(client, {"ids": ids, "settings": plain}).json()["queued"] == 3
    assert parked() == [(snap, None), (None, None), (None, None)]  # tệp error tại chỗ: config về NULL
    # Áp một cài đặt với động cơ AI: mọi tệp giữ snapshot hiện có — đổi model hàng loạt không mất ngữ cảnh riêng.
    reset()
    ai = {"language": "vi", "engine": "gemini", "model": "gemini-3.8-flash", "font": "auto"}
    assert bulk_retranslate(client, {"ids": ids, "settings": ai}).json()["queued"] == 3
    assert parked() == [(snap, snap), (snap, None), (None, None)]
    # Chế độ nâng cao tắt: không giữ gì.
    reset()
    assert client.put("/api/settings/preferences", json={"default_engine": "google_free", "advance_mode": False}).status_code == 200
    assert bulk_retranslate(client, {"ids": ids, "settings": None}).json()["queued"] == 3
    assert parked() == [(snap, None), (None, None), (None, None)]


# ---- Phiên bản (spec 2026-10-14 §5, §7) ------------------------------------------------------------------------


def test_file_detail_lists_versions_newest_first_and_serves_an_old_one(client, me):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    first = client.get(f"/api/files/{file_id}/download").content
    item = client.get(f"/api/files/{file_id}").json()
    assert item["version_no"] == 1 and item["versions"] == []
    assert "versions" not in client.get("/api/files").json()["items"][0]  # danh sách chỉ có version_no
    assert retranslate(client, file_id, language="en", font="serif").status_code == 202
    wait_file(client, file_id)
    assert retranslate(client, file_id, language="vi", font="sans").status_code == 202
    detail = wait_file(client, file_id)
    assert detail["version_no"] == 3 and [version["version_no"] for version in detail["versions"]] == [2, 1]
    v1 = detail["versions"][1]
    assert (v1["language"], v1["engine"], v1["model"], v1["font"], v1["available"], v1["config"]) == ("vi", "google_free", None, "auto", True, None)
    assert v1["archived_at"].endswith("Z") and v1["finished_at"] is None
    response = client.get(f"/api/files/{file_id}/versions/{v1['id']}/download")
    assert response.status_code == 200 and response.content == first
    assert "doc-vi-v1.pdf" in response.headers["content-disposition"] and response.headers["cache-control"] == "no-store"
    inline = client.get(f"/api/files/{file_id}/versions/{v1['id']}/download", params={"inline": 1})
    assert inline.headers["content-disposition"].startswith("inline") and inline.headers["x-content-type-options"] == "nosniff"


def test_version_download_is_scoped_to_the_file_and_its_owner_and_reports_missing_files(client, me, sign_up, settings):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    retranslate(client, file_id, language="en")
    [version] = wait_file(client, file_id)["versions"]
    other_file = upload(client, "khac.pdf").json()["id"]
    wait_file(client, other_file)
    response = client.get(f"/api/files/{other_file}/versions/{version['id']}/download")
    assert response.status_code == 404 and response.json() == {"detail": {"code": "version_not_found"}}
    assert client.get(f"/api/files/{file_id}/versions/nope00000000/download").status_code == 404
    (file_dir(settings.users_dir, me["id"], file_id) / "versions" / version["id"] / "doc-vi.pdf").unlink()
    assert client.get(f"/api/files/{file_id}").json()["versions"][0]["available"] is False
    gone = client.get(f"/api/files/{file_id}/versions/{version['id']}/download")
    assert gone.status_code == 410 and gone.json() == {"detail": {"code": "gone"}}
    sign_up("binh@example.com")
    assert client.get(f"/api/files/{file_id}/versions/{version['id']}/download").json() == {"detail": {"code": "not_found"}}  # tệp của người khác


def test_deleting_a_file_removes_its_version_rows_and_folder(client, me, settings):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    retranslate(client, file_id, language="en")
    assert len(wait_file(client, file_id)["versions"]) == 1
    directory = file_dir(settings.users_dir, me["id"], file_id)
    assert (directory / "versions").is_dir()
    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert not directory.exists()
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FileVersion).where(FileVersion.file_id == file_id)) == 0  # FK CASCADE


def test_items_carry_translated_at_and_the_restore_fields_and_versions_inherit_them(client, me):
    assert upload(client, "b.pdf").json()["translated_at"] is None  # chưa xong
    file_id = upload(client, "doc.pdf").json()["id"]
    first = wait_file(client, file_id)
    assert first["translated_at"] == first["finished_at"] and first["translated_at"].endswith("Z")
    assert (first["restored_from"], first["restoring"], first["restore_version"]) == (None, False, None)
    listed = next(item for item in client.get("/api/files").json()["items"] if item["id"] == file_id)
    assert (listed["translated_at"], listed["restoring"], listed["restored_from"]) == (first["translated_at"], False, None)
    assert retranslate(client, file_id, language="en").status_code == 202
    detail = wait_file(client, file_id)
    [version] = detail["versions"]
    assert (version["translated_at"], version["restored_from"]) == (first["translated_at"], None)
    assert detail["translated_at"] >= first["translated_at"]


def test_version_items_say_whether_their_segment_table_travelled_with_them(client, me, settings):
    save_key(client, "gemini")
    file_id = upload(client, "newtable.pdf", engine="gemini").json()["id"]  # lần dịch đầu: worker giả KHÔNG ghi bảng
    wait_file(client, file_id)
    assert retranslate(client, file_id, language="en", engine="gemini", model="gemini-3.5-flash-lite").status_code == 202
    wait_file(client, file_id)  # dịch lại: worker giả ghi bảng mới vào rebuild/ → bản 2 (bản hiện tại lúc này) có bảng
    assert retranslate(client, file_id, language="vi", engine="gemini", model="gemini-3.5-flash-lite").status_code == 202
    newest, oldest = wait_file(client, file_id)["versions"]
    assert (newest["version_no"], newest["has_tables"]) == (2, True)
    assert (oldest["version_no"], oldest["has_tables"]) == (1, False)
    assert (file_dir(settings.users_dir, me["id"], file_id) / "versions" / newest["id"] / "segments.jsonl").is_file()


# ---- Khôi phục bản cũ (spec 2026-10-15 §2, §8) ------------------------------------------------------------------


def restore(client, file_id, version_id):
    return client.post(f"/api/files/{file_id}/versions/{version_id}/restore")


def test_restore_copies_an_old_version_into_place_as_a_new_version_and_the_item_says_so_meanwhile(client, me):
    file_id = upload(client, "doc.pdf").json()["id"]
    first = wait_file(client, file_id)
    first_pdf = client.get(f"/api/files/{file_id}/download").content
    assert retranslate(client, file_id, language="en", font="serif").status_code == 202
    [v1] = wait_file(client, file_id)["versions"]
    blocker = upload(client, "slow.pdf").json()["id"]  # worker giả ngủ 3 s: lượt khôi phục xếp hàng sau nó, phản hồi chắc chắn "queued"
    wait_file(client, blocker, statuses=("running",))
    response = restore(client, file_id, v1["id"])
    assert response.status_code == 202, response.text
    queued = response.json()
    assert (queued["status"], queued["restoring"], queued["restore_version"], queued["retranslating"]) == ("queued", True, v1["id"], True)
    assert queued["retranslate_to"] == {"language": "vi", "engine": "google_free", "model": None, "font": "auto"}
    done = wait_file(client, file_id)
    assert (done["version_no"], done["restored_from"], done["language"], done["font"], done["restoring"], done["restore_version"]) == (
        3, 1, "vi", "auto", False, None)
    assert done["translated_at"] >= first["translated_at"] and done["config"] is None
    assert [(version["version_no"], version["restored_from"]) for version in done["versions"]] == [(2, None), (1, None)]
    assert client.get(f"/api/files/{file_id}/download").content == first_pdf  # bản sao của Bản 1
    assert next(item for item in client.get("/api/files").json()["items"] if item["id"] == file_id)["restoring"] is False
    wait_file(client, blocker)


def test_restore_is_refused_for_unknown_versions_full_queues_missing_files_pending_files_and_other_people(client, me, sign_up, settings):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    assert retranslate(client, file_id, language="en").status_code == 202
    [version] = wait_file(client, file_id)["versions"]
    other_file = upload(client, "khac.pdf").json()["id"]
    wait_file(client, other_file)
    assert restore(client, other_file, version["id"]).json() == {"detail": {"code": "version_not_found"}}
    assert restore(client, file_id, "nope00000000").status_code == 404
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = 0
        db.commit()
    full = restore(client, file_id, version["id"])
    assert full.status_code == 429 and full.json() == {"detail": {"code": "too_many_pending", "limit": 0}}
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = None
        db.commit()
    path = file_dir(settings.users_dir, me["id"], file_id) / "versions" / version["id"] / "doc-vi.pdf"
    data = path.read_bytes()
    path.unlink()
    gone = restore(client, file_id, version["id"])
    assert gone.status_code == 410 and gone.json() == {"detail": {"code": "gone"}}
    path.write_bytes(data)
    client.app.state.runner.stop()  # trạng thái chèn tay phải đứng yên
    for status in ("error", "queued", "running"):
        with client.app.state.session_factory() as db:
            db.execute(update(File).where(File.id == file_id).values(status=status))
            db.commit()
        refused = restore(client, file_id, version["id"])
        assert refused.status_code == 409 and refused.json() == {"detail": {"code": "not_restorable"}}
    with client.app.state.session_factory() as db:
        db.execute(update(File).where(File.id == file_id).values(status="done"))
        db.commit()
    item = client.get(f"/api/files/{file_id}").json()
    assert (item["status"], item["restoring"]) == ("done", False)  # không có gì bị xếp hàng
    sign_up("binh@example.com")
    assert restore(client, file_id, version["id"]).json() == {"detail": {"code": "not_found"}}


def test_restore_refuses_a_file_the_runner_takes_between_the_checks_and_the_update(client, me, monkeypatch):
    """UPDATE có điều kiện `status='done'`: luồng chạy / lượt bấm khác đổi trạng thái SAU mọi phép kiểm → 409, không xếp gì."""
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    assert retranslate(client, file_id, language="en").status_code == 202
    [version] = wait_file(client, file_id)["versions"]
    client.app.state.runner.stop()
    real = service._check_pending

    def racing(db, cfg, user_id):
        real(db, cfg, user_id)  # mọi phép kiểm đã qua …
        with client.app.state.session_factory() as other:  # … rồi runner nhận tệp ngay trước UPDATE
            other.execute(update(File).where(File.id == file_id).values(status="running"))
            other.commit()

    monkeypatch.setattr(service, "_check_pending", racing)
    response = restore(client, file_id, version["id"])
    assert response.status_code == 409 and response.json() == {"detail": {"code": "not_restorable"}}
    with client.app.state.session_factory() as db:
        row = db.get(File, file_id)
        assert (row.status, row.restore_version, row.rebuild_font, row.retranslate_language, row.retranslate_engine) == (
            "running", None, None, None, None)


def test_list_paginates_newest_first(client, me):
    seed(client, me["id"], [f"tệp {index:02d}.pdf" for index in range(25)])
    first = client.get("/api/files", params={"page": 1, "page_size": 20}).json()
    assert first["total"] == 25 and first["page"] == 1 and first["page_size"] == 20
    assert len(first["items"]) == 20 and first["items"][0]["filename"] == "tệp 24.pdf"
    second = client.get("/api/files", params={"page": 2, "page_size": 20}).json()
    assert [item["filename"] for item in second["items"]] == [f"tệp {index:02d}.pdf" for index in range(4, -1, -1)]
    assert client.get("/api/files", params={"page_size": 101}).status_code == 422
    assert client.get("/api/files", params={"page": 0}).status_code == 422


def test_search_ignores_case_and_unicode_form(client, me):
    seed(client, me["id"], ["Báo cáo tài chính.pdf", "Hợp đồng.pdf"])
    uploaded = upload(client, unicodedata.normalize("NFD", "Biên bản họp.pdf")).json()
    assert uploaded["filename"] == unicodedata.normalize("NFC", "Biên bản họp.pdf")
    assert names(client, "BÁO CÁO") == ["Báo cáo tài chính.pdf"]
    assert names(client, "HỌP") == ["Biên bản họp.pdf"]
    assert names(client, unicodedata.normalize("NFD", "đồng")) == ["Hợp đồng.pdf"]


def test_search_treats_wildcards_literally(client, me):
    seed(client, me["id"], ["50%_off.pdf", "500 off.pdf", "a_b.pdf", "ab.pdf"])
    assert names(client, "50%") == ["50%_off.pdf"]
    assert names(client, "a_b") == ["a_b.pdf"]


def test_other_users_files_are_invisible(client, sign_up):
    sign_up("an@example.com")
    file_id = upload(client, "rieng-tu.pdf").json()["id"]
    wait_file(client, file_id)
    sign_up("binh@example.com")
    assert client.get("/api/files").json()["total"] == 0
    for method, path in [
        ("GET", f"/api/files/{file_id}"),
        ("GET", f"/api/files/{file_id}/download?kind=original"),
        ("GET", f"/api/files/{file_id}/download?kind=original&inline=1"),
        ("POST", f"/api/files/{file_id}/retranslate"),
        ("POST", f"/api/files/{file_id}/rebuild"),
        ("DELETE", f"/api/files/{file_id}"),
    ]:
        bodies = {"rebuild": {"font": "sans"}, "retranslate": {"language": "vi", "engine": "google_free", "font": "auto"}}
        response = client.request(method, path, json=bodies.get(path.rsplit("/", 1)[-1]))
        assert response.status_code == 404, (method, path)
        assert response.json() == {"detail": {"code": "not_found"}}


def test_download_translated_and_original(client, me):
    file_id = upload(client, "Báo cáo.pdf").json()["id"]
    wait_file(client, file_id)
    translated = client.get(f"/api/files/{file_id}/download")
    assert translated.status_code == 200 and translated.content.startswith(b"%PDF-")
    assert translated.headers["content-type"] == "application/pdf"
    assert translated.headers["content-disposition"].startswith("attachment")
    assert "filename*=utf-8''B%C3%A1o%20c%C3%A1o-vi.pdf" in translated.headers["content-disposition"]
    assert translated.headers["x-content-type-options"] == "nosniff"
    # Dựng lại thay tệp tại chỗ (cùng URL): trình duyệt không được giữ bản PDF cũ trong cache.
    assert translated.headers["cache-control"] == "no-store"
    original = client.get(f"/api/files/{file_id}/download", params={"kind": "original"})
    assert original.status_code == 200
    assert original.headers["content-disposition"].startswith("attachment")
    assert "filename*=utf-8''B%C3%A1o%20c%C3%A1o.pdf" in original.headers["content-disposition"]
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.headers["cache-control"] == "no-store"


def test_download_inline_keeps_filename_and_sets_inline_disposition(client, me):
    file_id = upload(client, "Báo cáo.pdf").json()["id"]
    wait_file(client, file_id)
    translated = client.get(f"/api/files/{file_id}/download", params={"inline": 1})
    assert translated.status_code == 200 and translated.content.startswith(b"%PDF-")
    disposition = translated.headers["content-disposition"]
    assert disposition.startswith("inline")
    assert "filename*=utf-8''B%C3%A1o%20c%C3%A1o-vi.pdf" in disposition
    assert translated.headers["x-content-type-options"] == "nosniff"
    assert translated.headers["cache-control"] == "no-store"  # "Mở trong tab mới" sau khi dựng lại
    original = client.get(f"/api/files/{file_id}/download", params={"kind": "original", "inline": 1})
    assert original.status_code == 200
    original_disposition = original.headers["content-disposition"]
    assert original_disposition.startswith("inline")
    assert "filename*=utf-8''B%C3%A1o%20c%C3%A1o.pdf" in original_disposition
    assert original.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("inline", [0, 1])
def test_download_before_done_and_after_disk_loss(client, me, settings, inline):
    file_id = upload(client, "slow.pdf").json()["id"]
    early = client.get(f"/api/files/{file_id}/download", params={"inline": inline})
    assert early.status_code == 409 and early.json() == {"detail": {"code": "not_ready"}}
    wait_file(client, file_id)
    (file_dir(settings.users_dir, me["id"], file_id) / "slow-vi.pdf").unlink()
    gone = client.get(f"/api/files/{file_id}/download", params={"inline": inline})
    assert gone.status_code == 410 and gone.json() == {"detail": {"code": "gone"}}


def test_delete_removes_row_and_files(client, me, settings):
    file_id = upload(client).json()["id"]
    wait_file(client, file_id)
    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert client.get(f"/api/files/{file_id}").status_code == 404
    assert not file_dir(settings.users_dir, me["id"], file_id).exists()


def test_delete_refuses_running_but_cancels_queued(client, me, settings):
    running = upload(client, "slow.pdf").json()["id"]
    queued = upload(client, "doc.pdf").json()["id"]
    wait_file(client, running, statuses=("running",))
    refused = client.delete(f"/api/files/{running}")
    assert refused.status_code == 409 and refused.json() == {"detail": {"code": "file_running"}}
    assert client.delete(f"/api/files/{queued}").status_code == 204
    wait_file(client, running)
    assert client.get(f"/api/files/{queued}").status_code == 404
    assert not file_dir(settings.users_dir, me["id"], queued).exists()


def test_path_tricks_in_filename_stay_inside_user_folder(client, me, settings):
    first = upload(client, "../../evil.pdf").json()
    second = upload(client, "..\\..\\evil.pdf").json()
    assert first["filename"] == second["filename"] == "evil.pdf"
    assert first["id"] != second["id"]
    for item in (first, second):
        assert (file_dir(settings.users_dir, me["id"], item["id"]) / "evil.pdf").is_file()
    assert not (settings.data_dir / "evil.pdf").exists()
    assert not (settings.users_dir / "evil.pdf").exists()


def test_disk_full_is_reported(client, me, monkeypatch):
    def full(*_args):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(service, "save_upload", full)
    response = upload(client)
    assert response.status_code == 507 and response.json() == {"detail": {"code": "disk_full"}}


def test_meta_lists_the_36_supported_languages(client, me):
    body = client.get("/api/meta").json()
    assert len(body["languages"]) == 36
    assert body["languages"][0] == {"code": "vi", "name": "Tiếng Việt"}
    assert body["default_language"] == "vi" and body["max_upload_mb"] == 50


def test_meta_exposes_the_source_link(client, me):
    assert client.get("/api/meta").json()["source_url"] == ""
    client.app.state.settings = replace(client.app.state.settings, source_url="https://git.example.com/pdf")
    assert client.get("/api/meta").json()["source_url"] == "https://git.example.com/pdf"


def test_upload_defaults_to_google_free_and_exposes_engine_fields(client, me):
    item = upload(client, "doc.pdf").json()
    assert (item["engine"], item["model"], item["stage"]) == ("google_free", None, "")
    done = wait_file(client, item["id"])
    assert (done["engine"], done["model"], done["stage"]) == ("google_free", None, "")
    assert client.get("/api/files").json()["items"][0]["engine"] == "google_free"


@pytest.mark.parametrize(("engine", "code"), [
    ("deepl", "unsupported_engine"), ("gemini", "missing_api_key"), ("google_cloud", "missing_api_key"),
])
def test_upload_rejects_engines_without_a_key(client, me, engine, code):
    response = upload(client, "doc.pdf", engine=engine)
    assert response.status_code == 400 and response.json() == {"detail": {"code": code}}
    assert client.get("/api/files").json()["total"] == 0


def test_upload_with_gemini_uses_the_default_model_and_rejects_unknown_ones(client, me):
    save_key(client, "gemini")
    assert client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": "gemini-3.8-flash"}).status_code == 200
    item = upload(client, "doc.pdf").json()  # không truyền engine: theo mặc định của user
    assert (item["engine"], item["model"]) == ("gemini", "gemini-3.8-flash")
    wait_file(client, item["id"])
    explicit = upload(client, "doc.pdf", engine="gemini", model="gemini-3.5-flash-lite").json()
    assert explicit["model"] == "gemini-3.5-flash-lite"
    wait_file(client, explicit["id"])
    bad = upload(client, "doc.pdf", engine="gemini", model="gemini-3.1-pro-preview")
    assert bad.status_code == 400 and bad.json() == {"detail": {"code": "unsupported_model"}}
    plain = upload(client, "doc.pdf", engine="google_free", model="gemini-3.8-flash").json()
    assert (plain["engine"], plain["model"]) == ("google_free", None)


def test_rotated_secret_key_blocks_uploads_with_that_engine(client, me):
    save_key(client, "gemini")
    client.app.state.settings = replace(client.app.state.settings, secret_key="t" * 32)
    response = upload(client, "doc.pdf", engine="gemini")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "missing_api_key"}}


def test_handoff_job_runs_with_the_key_in_the_environment_only(client, me, settings):
    save_key(client, "gemini")
    item = upload(client, "doc.pdf", engine="gemini").json()
    done = wait_file(client, item["id"])
    assert done["status"] == "done", done["message"]
    assert (done["untranslated"], done["stage"], done["done_pages"], done["total_pages"]) == (1, "", 2, 2)
    directory = file_dir(settings.users_dir, me["id"], item["id"])
    seen = json.loads((directory / "env-seen.json").read_text(encoding="utf-8"))
    assert (seen["provider"], seen["model"], seen["api_key"]) == ("gemini", "gemini-3.5-flash-lite", "AIza-test-key-0001")
    assert seen["argv"] == [str(directory / "doc.pdf"), str(directory), "vi"]  # key không qua argv
    assert "AIza" not in (directory / "worker-stderr.log").read_text(encoding="utf-8")
    assert "AIza" not in done["message"]


def test_job_without_a_usable_key_fails_before_running_the_worker(client, me, settings):
    save_key(client, "gemini")
    upload(client, "slow.pdf")  # worker giả (google_free) ngủ 3 s: tệp gemini phía sau còn nằm chờ
    item = upload(client, "doc.pdf", engine="gemini").json()
    assert client.delete("/api/settings/credentials/gemini").status_code == 204
    failed = wait_file(client, item["id"])
    assert failed["status"] == "error"
    assert failed["message"] == "Chưa có API key cho Gemini (Google AI Studio). Thêm key trong Cài đặt rồi bấm Dịch lại."
    assert not (file_dir(settings.users_dir, me["id"], item["id"]) / "env-seen.json").exists()
    assert (failed["engine"], failed["model"]) == ("gemini", "gemini-3.5-flash-lite")  # Dịch lại dùng lại engine đã lưu
    save_key(client, "gemini")
    retried = retranslate(client, item["id"], engine=failed["engine"], model=failed["model"])  # tệp lỗi: dịch lại tại chỗ
    assert retried.status_code == 202 and retried.json()["stage"] == ""
    again = wait_file(client, item["id"])
    assert again["status"] == "done" and (again["engine"], again["model"]) == ("gemini", "gemini-3.5-flash-lite")


def test_meta_lists_engines_and_gemini_models(client, me):
    body = client.get("/api/meta").json()
    assert [e["id"] for e in body["engines"]] == ["google_free", "google_cloud", "gemini"]
    assert "available" not in body["engines"][0] and body["engines"][2]["needs_key"] is True
    assert body["engines"][2]["label"] == "Gemini (Google AI Studio)"
    assert [m["id"] for m in body["gemini_models"]][:2] == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]


# ---- Font bản dịch + "Dựng lại với font khác" (spec 2026-10-02 §5) -----------------------------

def rebuild(client, file_id, font="serif"):
    return client.post(f"/api/files/{file_id}/rebuild", json={"font": font})


def test_upload_uses_the_default_font_and_exposes_the_font_fields(client, me):
    item = upload(client, "doc.pdf").json()
    assert {key: item[key] for key in ("font", "font_used", "rebuild_font", "rebuilding", "rebuild_error")} == {
        "font": "auto", "font_used": None, "rebuild_font": None, "rebuilding": False, "rebuild_error": ""}
    done = wait_file(client, item["id"])
    assert (done["font"], done["font_used"]) == ("auto", None)  # worker giả không phát dòng font


def test_upload_takes_an_explicit_font_or_the_saved_default(client, me):
    client.put("/api/settings/preferences", json={"default_engine": "google_free", "default_font": "serif"})
    follows = upload(client, "a.pdf").json()
    explicit = upload(client, "b.pdf", font="sans").json()
    assert (follows["font"], explicit["font"]) == ("serif", "sans")
    wait_file(client, follows["id"])
    wait_file(client, explicit["id"])


def test_upload_rejects_an_unknown_font(client, me, settings):
    response = upload(client, "doc.pdf", font="comic")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "unsupported_font"}}
    assert client.get("/api/files").json()["total"] == 0
    assert not (settings.users_dir / me["id"]).exists()  # kiểm font TRƯỚC khi ghi gì xuống đĩa


def test_the_chosen_font_reaches_the_worker_and_comes_back_as_font_used(client, me, settings):
    item = upload(client, "fontline.pdf", font="serif").json()
    done = wait_file(client, item["id"])
    assert (done["font"], done["font_used"]) == ("serif", "serif")
    seen = json.loads((file_dir(settings.users_dir, me["id"], item["id"]) / "env-seen.json").read_text(encoding="utf-8"))
    assert seen["font"] == "serif"


def test_rebuild_requeues_a_done_file_and_keeps_the_old_translation_downloadable(client, me, settings):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    old = client.get(f"/api/files/{file_id}/download").content
    blocker = upload(client, "slow.pdf").json()["id"]  # worker giả ngủ 3 s: lượt dựng lại phải xếp hàng sau nó
    wait_file(client, blocker, statuses=("running",))
    response = rebuild(client, file_id, "serif")
    assert response.status_code == 202
    item = response.json()
    assert (item["status"], item["rebuilding"], item["rebuild_font"], item["font"]) == ("queued", True, "serif", "auto")
    assert (item["done_pages"], item["total_pages"], item["rebuild_error"]) == (0, 0, "")
    during = client.get(f"/api/files/{file_id}/download")
    assert during.status_code == 200 and during.content == old  # bản cũ vẫn tải được trong lúc chờ dựng lại
    assert client.get(f"/api/files/{file_id}/download", params={"inline": 1}).status_code == 200
    done = wait_file(client, file_id)
    assert (done["status"], done["font"], done["rebuilding"], done["rebuild_font"]) == ("done", "serif", False, None)
    assert client.get(f"/api/files/{file_id}/download").content.endswith(b"% rebuilt font=serif\n")
    wait_file(client, blocker)


def test_only_done_files_can_be_rebuilt(client, me):
    failed = upload(client, "fail.pdf").json()["id"]
    wait_file(client, failed)
    response = rebuild(client, failed)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "not_rebuildable"}}
    pending = upload(client, "slow.pdf").json()["id"]
    assert rebuild(client, pending).status_code == 409
    wait_file(client, pending)


def test_rebuild_rejects_an_unknown_font(client, me):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    response = rebuild(client, file_id, "comic")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "unsupported_font"}}
    assert client.get(f"/api/files/{file_id}").json()["rebuilding"] is False


def test_rebuild_takes_a_pending_slot(client, me):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    for index in range(3):
        assert upload(client, f"slow-{index}.pdf").status_code == 202
    response = rebuild(client, file_id)
    assert response.status_code == 429 and response.json() == {"detail": {"code": "too_many_pending", "limit": 3}}
    assert client.get(f"/api/files/{file_id}").json()["status"] == "done"


def test_a_queued_rebuild_is_deleted_like_any_queued_file(client, me, settings):
    file_id = upload(client, "doc.pdf").json()["id"]
    wait_file(client, file_id)
    blocker = upload(client, "slow.pdf").json()["id"]
    wait_file(client, blocker, statuses=("running",))
    assert rebuild(client, file_id).json()["status"] == "queued"
    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert client.get(f"/api/files/{file_id}").status_code == 404
    assert not file_dir(settings.users_dir, me["id"], file_id).exists()
    wait_file(client, blocker)


def test_upload_by_an_account_deleted_mid_flight_is_a_401_and_leaves_nothing_on_disk(client, me, settings, monkeypatch):
    factory = client.app.state.session_factory
    real_check = service._check_pending

    def delete_account_then_check(db, cfg, user_id):
        real_check(db, cfg, user_id)
        with factory() as other:  # tab/thiết bị khác xoá tài khoản giữa lúc xác thực và lúc ghi dòng
            other.execute(delete(User).where(User.id == user_id))
            other.commit()

    monkeypatch.setattr(service, "_check_pending", delete_account_then_check)
    response = upload(client, "doc.pdf")
    assert response.status_code == 401 and response.json() == {"detail": {"code": "unauthenticated"}}
    user_dir = settings.users_dir / me["id"]
    assert not user_dir.exists() or not any(user_dir.iterdir())  # không còn thư mục job mồ côi


def seed_rows(client, user_id, rows, prefix="row") -> list[str]:
    """rows: (tên, trạng thái, giây-từ-gốc). Trả về id theo thứ tự đã chèn; thư mục đĩa được tạo sẵn."""
    start = utcnow() - timedelta(hours=2)
    ids = []
    settings = client.app.state.settings
    if any(status in ("queued", "running") for _name, status, _second in rows):
        client.app.state.runner.stop()  # runner thật poll mỗi 1 s: không để nó nhận tệp chèn thẳng (an toàn khi gọi hai lần)
    with client.app.state.session_factory() as db:
        for index, (name, status, second) in enumerate(rows):
            file_id = f"{prefix}{index:08d}"
            db.add(File(id=file_id, user_id=user_id, filename=name, search_name=service.normalize_search(name),
                        language="vi", status=status, created_at=start + timedelta(seconds=second)))
            file_dir(settings.users_dir, user_id, file_id).mkdir(parents=True, exist_ok=True)
            ids.append(file_id)
        db.commit()
    return ids


def listed(client, **params) -> list[str]:
    return [item["filename"] for item in client.get("/api/files", params=params).json()["items"]]


SORT_ROWS = [("b.pdf", "done", 0), ("C.pdf", "error", 1), ("a.pdf", "queued", 2), ("d.pdf", "running", 3),
             ("Á.pdf", "done", 4)]


def test_list_sorts_by_created_by_default_and_both_directions(client, me):
    seed_rows(client, me["id"], SORT_ROWS)
    newest = ["Á.pdf", "d.pdf", "a.pdf", "C.pdf", "b.pdf"]
    assert listed(client) == newest
    assert listed(client, sort="created", dir="desc") == newest
    assert listed(client, sort="created", dir="asc") == newest[::-1]
    assert listed(client, dir="asc") == newest[::-1]


def test_list_sorts_by_name_ignoring_case_and_accents(client, me):
    seed_rows(client, me["id"], SORT_ROWS)
    asc = listed(client, sort="name", dir="asc")
    assert asc == ["a.pdf", "Á.pdf", "b.pdf", "C.pdf", "d.pdf"]
    assert listed(client, sort="name", dir="desc") == asc[::-1]


def test_list_sorts_by_status_rank(client, me):
    seed_rows(client, me["id"], SORT_ROWS)
    # queued 0, running 1, error 2, done 3; cùng hạng -> mới nhất trước
    assert listed(client, sort="status", dir="asc") == ["a.pdf", "d.pdf", "C.pdf", "Á.pdf", "b.pdf"]
    # desc đảo hạng nhưng tie-breaker vẫn created_at desc
    assert listed(client, sort="status", dir="desc") == ["Á.pdf", "b.pdf", "C.pdf", "d.pdf", "a.pdf"]


def test_sorted_paging_is_stable_with_ties(client, me):
    # 7 tệp cùng tên + cùng thời điểm tạo: chỉ id desc phân biệt -> các trang không trùng, không sót.
    start = utcnow() - timedelta(hours=1)
    with client.app.state.session_factory() as db:
        for index in range(7):
            db.add(File(id=f"tie{index:09d}", user_id=me["id"], filename="same.pdf", search_name="same.pdf",
                        language="vi", status="done", created_at=start))
        db.commit()
    for sort in ("created", "name", "status"):
        for direction in ("asc", "desc"):
            seen = []
            for page in (1, 2, 3):
                body = client.get("/api/files", params={"sort": sort, "dir": direction, "page": page,
                                                        "page_size": 3}).json()
                seen += [item["id"] for item in body["items"]]
            assert seen == sorted(seen, reverse=True) and len(set(seen)) == 7, (sort, direction)


def test_list_sort_combines_with_filter(client, me):
    seed_rows(client, me["id"], [("rpt-b.pdf", "done", 0), ("rpt-a.pdf", "done", 1), ("other.pdf", "done", 2)])
    assert listed(client, q="rpt", sort="name", dir="asc") == ["rpt-a.pdf", "rpt-b.pdf"]
    assert client.get("/api/files", params={"q": "rpt", "sort": "name"}).json()["total"] == 2


@pytest.mark.parametrize("params", [{"sort": "size"}, {"dir": "up"}, {"sort": ""}, {"dir": "ASC"}])
def test_list_rejects_invalid_sort_or_dir(client, me, params):
    response = client.get("/api/files", params=params)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "validation"}}


def bulk(client, body):
    return client.post("/api/files/bulk-delete", json=body)


def remaining(client) -> set[str]:
    with client.app.state.session_factory() as db:
        return {row.id for row in db.scalars(select(File))}


def foreign_file(client, sign_up, mine) -> tuple[str, str]:
    """Tệp của người khác (rồi quay lại tài khoản của mình): (id người đó, id tệp)."""
    other = sign_up("binh@example.com")["id"]
    file_id = seed_rows(client, other, [("x.pdf", "done", 0)], prefix="oth")[0]
    assert client.post("/api/auth/login", json={"email": mine, "password": "mat-khau-8"}).status_code == 200
    return other, file_id


def test_bulk_delete_by_ids_counts_and_removes_only_deleted(client, me, settings, sign_up):
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "error", 1), ("3.pdf", "queued", 2),
                                       ("4.pdf", "running", 3), ("5.pdf", "done", 4)])
    other, foreign = foreign_file(client, sign_up, "an@example.com")
    response = bulk(client, {"ids": [ids[0], ids[1], ids[2], ids[3], foreign, "nope00000000"]})
    assert response.status_code == 200 and response.json() == {"deleted": 3, "skipped_running": 1}
    assert remaining(client) == {ids[3], ids[4], foreign}
    for index in (0, 1, 2):
        assert not file_dir(settings.users_dir, me["id"], ids[index]).exists()
    assert file_dir(settings.users_dir, me["id"], ids[3]).exists()
    assert file_dir(settings.users_dir, me["id"], ids[4]).exists()
    assert file_dir(settings.users_dir, other, foreign).exists()


def test_bulk_delete_only_foreign_or_unknown_ids_reveals_nothing(client, me, sign_up):
    other, foreign = foreign_file(client, sign_up, "an@example.com")
    response = bulk(client, {"ids": [foreign, "nope00000000"]})
    assert response.status_code == 200 and response.json() == {"deleted": 0, "skipped_running": 0}
    assert foreign in remaining(client)


def test_bulk_delete_all_with_filter_only_touches_matches(client, me, settings, sign_up):
    ids = seed_rows(client, me["id"], [("Báo cáo 1.pdf", "done", 0), ("BÁO CÁO 2.pdf", "error", 1),
                                       ("Báo cáo 3.pdf", "running", 2), ("Khác.pdf", "done", 3)])
    other, foreign = foreign_file(client, sign_up, "an@example.com")
    response = bulk(client, {"all": True, "q": "  báo cáo "})
    assert response.json() == {"deleted": 2, "skipped_running": 1}
    assert remaining(client) == {ids[2], ids[3], foreign}
    assert not file_dir(settings.users_dir, me["id"], ids[0]).exists()
    assert file_dir(settings.users_dir, me["id"], ids[3]).exists()


def test_bulk_delete_all_with_empty_q_deletes_every_own_file(client, me, settings, sign_up):
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "queued", 1), ("3.pdf", "running", 2)])
    other, foreign = foreign_file(client, sign_up, "an@example.com")
    for body in ({"all": True, "q": ""}, {"all": True}):
        response = bulk(client, body)
        assert response.status_code == 200
        assert response.json() == ({"deleted": 2, "skipped_running": 1} if "q" in body
                                   else {"deleted": 0, "skipped_running": 1})
    assert remaining(client) == {ids[2], foreign}
    assert bulk(client, {"all": True}).json() == {"deleted": 0, "skipped_running": 1}


def test_bulk_delete_wildcards_in_q_are_literal(client, me):
    seed_rows(client, me["id"], [("50%_off.pdf", "done", 0), ("500 off.pdf", "done", 1)])
    assert bulk(client, {"all": True, "q": "50%"}).json() == {"deleted": 1, "skipped_running": 0}
    assert listed(client) == ["500 off.pdf"]


def test_bulk_delete_skips_a_file_that_turns_running_before_deletion(client, me, settings, monkeypatch):
    ids = seed_rows(client, me["id"], [("1.pdf", "queued", 0), ("2.pdf", "queued", 1)])
    real = service.try_delete_file

    def racing(db, cfg, user_id, file_id):
        if file_id == ids[0]:  # luồng chạy nhận tệp ngay trước khi xoá
            with client.app.state.session_factory() as other:
                other.execute(update(File).where(File.id == ids[0]).values(status="running"))
                other.commit()
        return real(db, cfg, user_id, file_id)

    monkeypatch.setattr(service, "try_delete_file", racing)
    assert bulk(client, {"ids": ids}).json() == {"deleted": 1, "skipped_running": 1}
    assert remaining(client) == {ids[0]}
    assert file_dir(settings.users_dir, me["id"], ids[0]).exists()


@pytest.mark.parametrize("body", [
    {}, {"ids": []}, {"ids": ["a"], "all": True}, {"ids": ["a"], "q": "x"}, {"all": False}, {"all": "yes"},
    {"all": None}, {"all": 1}, {"q": "x"}, {"ids": ["a", "a"]}, {"ids": [f"id{n}" for n in range(101)]}, {"ids": "a"},
    {"ids": [1]}, {"all": True, "q": "x" * 201}, {"all": True, "extra": 1},
])
def test_bulk_delete_rejects_bad_bodies(client, me, body):
    seed_rows(client, me["id"], [("1.pdf", "done", 0)])
    response = bulk(client, body)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "validation"}}
    assert listed(client) == ["1.pdf"]


def test_bulk_delete_accepts_exactly_100_ids(client, me):
    ids = seed_rows(client, me["id"], [(f"{n}.pdf", "done", n) for n in range(100)])
    assert bulk(client, {"ids": ids}).json() == {"deleted": 100, "skipped_running": 0}


def test_bulk_delete_needs_login_and_csrf_header(client, me):
    seed_rows(client, me["id"], [("1.pdf", "done", 0)])
    forged = client.post("/api/files/bulk-delete", json={"all": True}, headers={"X-Requested-With": ""})
    assert forged.status_code == 403 and forged.json() == {"detail": {"code": "csrf"}}
    assert listed(client) == ["1.pdf"]
    client.cookies.clear()
    assert bulk(client, {"all": True}).status_code == 401


def test_name_sort_is_vietnamese_aware(client, me):
    seed_rows(client, me["id"], [(name, "done", n) for n, name in enumerate(
        ["Zalo.pdf", "Đơn hàng.pdf", "ánh sáng.pdf", "Báo cáo.pdf", "bảng.pdf", "an.pdf"])])
    asc = listed(client, sort="name", dir="asc")
    assert asc == ["an.pdf", "ánh sáng.pdf", "bảng.pdf", "Báo cáo.pdf", "Đơn hàng.pdf", "Zalo.pdf"]
    assert listed(client, sort="name", dir="desc") == asc[::-1]


def test_name_collation_is_deterministic_for_accent_variants():
    from app.db import vi_collation
    assert vi_collation("a", "á") == -1 and vi_collation("á", "a") == 1 and vi_collation("á", "á") == 0
    assert vi_collation("đ", "d") == 1 and vi_collation("d", "e") == -1


def test_bulk_delete_underscore_in_q_is_literal(client, me):
    seed_rows(client, me["id"], [("a_b.pdf", "done", 0), ("ab.pdf", "done", 1), ("axb.pdf", "done", 2)])
    assert bulk(client, {"all": True, "q": "a_b"}).json() == {"deleted": 1, "skipped_running": 0}
    assert sorted(listed(client)) == ["ab.pdf", "axb.pdf"]


def test_bulk_delete_with_rebuilds(client, me, settings):
    ids = seed_rows(client, me["id"], [("q.pdf", "queued", 0), ("r.pdf", "running", 1)])
    with client.app.state.session_factory() as db:
        db.execute(update(File).where(File.id.in_(ids)).values(rebuild_font="serif", output_name="out.pdf"))
        db.commit()
    for file_id in ids:
        (file_dir(settings.users_dir, me["id"], file_id) / "out.pdf").write_bytes(PDF)
    assert bulk(client, {"ids": ids}).json() == {"deleted": 1, "skipped_running": 1}
    assert not file_dir(settings.users_dir, me["id"], ids[0]).exists()
    assert (file_dir(settings.users_dir, me["id"], ids[1]) / "out.pdf").exists()
    assert remaining(client) == {ids[1]}


def test_a_row_deleted_by_another_request_is_gone_not_running(client, me, monkeypatch):
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "done", 1)])
    real = service.get_owned

    def vanishing(db, user_id, file_id):
        row = real(db, user_id, file_id)
        with client.app.state.session_factory() as other:  # xoá chen vào giữa get_owned và xoá
            other.execute(delete(File).where(File.id == file_id))
            other.commit()
        return row

    monkeypatch.setattr("app.files.router.service.get_owned", vanishing)
    gone = client.delete(f"/api/files/{ids[0]}")
    assert gone.status_code == 404 and gone.json() == {"detail": {"code": "not_found"}}
    monkeypatch.undo()
    # bulk: hàng biến mất giữa lúc chọn và lúc xoá không bị tính là "đang dịch"
    real_try = service.try_delete_file

    def racing(db, cfg, user_id, file_id):
        with client.app.state.session_factory() as other:
            other.execute(delete(File).where(File.id == file_id))
            other.commit()
        return real_try(db, cfg, user_id, file_id)

    monkeypatch.setattr(service, "try_delete_file", racing)
    assert bulk(client, {"ids": [ids[1]]}).json() == {"deleted": 0, "skipped_running": 0}


def test_bulk_delete_loads_no_file_objects(client, me, settings):
    """Chống tái phát độ phức tạp bậc hai: xoá hàng loạt không được nạp từng File vào session."""
    seed_rows(client, me["id"], [(f"{n}.pdf", "done", n) for n in range(300)])
    loaded = []

    def record(target, _context):
        loaded.append(target)

    event.listen(File, "load", record)
    try:
        with client.app.state.session_factory() as db:
            assert service.bulk_delete(db, settings, me["id"], ids=None, q="") == {"deleted": 300, "skipped_running": 0}
    finally:
        event.remove(File, "load", record)
    assert loaded == []


# ---- Dịch lại hàng loạt (spec 2026-10-05 §6) --------------------------------------------------------


def bulk_retranslate(client, body):
    return client.post("/api/files/bulk-retranslate", json=body)


def statuses(client, ids) -> dict:
    with client.app.state.session_factory() as db:
        return {file_id: db.get(File, file_id).status for file_id in ids}


def test_bulk_retranslate_by_ids_skips_pending_and_foreign_files(client, me, sign_up):
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "error", 1), ("3.pdf", "queued", 2), ("4.pdf", "running", 3)])
    other, foreign = foreign_file(client, sign_up, "an@example.com")
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = 5  # 2 tệp đang chờ/chạy + 2 chỗ trống: test này canh bỏ qua, không canh hạn
        db.commit()
    response = bulk_retranslate(client, {"ids": [*ids, foreign, "nope00000000"], "settings": None})
    assert response.status_code == 200 and response.json() == {"queued": 2, "skipped_pending": 2, "skipped_limit": 0, "limit": 5}
    with client.app.state.session_factory() as db:
        done_row, error_row, foreign_row = db.get(File, ids[0]), db.get(File, ids[1]), db.get(File, foreign)
        # giữ cài đặt riêng: tệp xong → dịch lại từ đầu với chính lựa chọn của nó, bản cũ giữ; tệp lỗi → tại chỗ
        assert (done_row.status, done_row.retranslate_language, done_row.retranslate_engine, done_row.rebuild_font, done_row.language) == (
            "queued", "vi", "google_free", "auto", "vi")
        assert (error_row.status, error_row.retranslate_language, error_row.language) == ("queued", None, "vi")
        assert foreign_row.status == "done"


def test_bulk_retranslate_respects_the_pending_limit_newest_first(client, me):
    ids = seed_rows(client, me["id"], [("cu.pdf", "done", 0), ("giua.pdf", "done", 1), ("moi.pdf", "done", 2), ("dang.pdf", "running", 3)])
    with client.app.state.session_factory() as db:
        instance_row(db).max_pending_per_user = 2
        db.commit()
    assert bulk_retranslate(client, {"all": True}).json() == {"queued": 1, "skipped_pending": 1, "skipped_limit": 2, "limit": 2}
    assert statuses(client, ids) == {ids[0]: "done", ids[1]: "done", ids[2]: "queued", ids[3]: "running"}  # mới nhất được chỗ


def test_bulk_retranslate_all_with_a_filter_only_touches_matches(client, me):
    ids = seed_rows(client, me["id"], [("Báo cáo 1.pdf", "done", 0), ("BÁO CÁO 2.pdf", "error", 1),
                                       ("Báo cáo 3.pdf", "running", 2), ("Khác.pdf", "done", 3)])
    assert bulk_retranslate(client, {"all": True, "q": "  báo cáo "}).json() == {"queued": 2, "skipped_pending": 1, "skipped_limit": 0, "limit": 3}
    assert statuses(client, ids) == {ids[0]: "queued", ids[1]: "queued", ids[2]: "running", ids[3]: "done"}


def test_bulk_retranslate_all_without_a_filter_leaves_other_users_files_alone(client, me, sign_up):
    """`all` với q rỗng: chỉ tệp của mình — tệp xong của người khác (tạo sau, mới nhất) không bị xếp, không được đếm."""
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "error", 1), ("3.pdf", "running", 2)])
    other, foreign = foreign_file(client, sign_up, "an@example.com")
    assert bulk_retranslate(client, {"all": True}).json() == {"queued": 2, "skipped_pending": 1, "skipped_limit": 0, "limit": 3}
    assert statuses(client, [*ids, foreign]) == {ids[0]: "queued", ids[1]: "queued", ids[2]: "running", foreign: "done"}
    with client.app.state.session_factory() as db:
        assert (db.get(File, foreign).retranslate_language, db.get(File, foreign).rebuild_font) == (None, None)


def test_bulk_retranslate_with_shared_settings_validates_once_and_applies_to_every_file(client, me):
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "error", 1), ("3.pdf", "queued", 2)])
    body = {"ids": ids, "settings": {"language": "en", "engine": "google_free", "model": None, "font": "serif"}}
    assert bulk_retranslate(client, body).json() == {"queued": 2, "skipped_pending": 1, "skipped_limit": 0, "limit": 3}
    with client.app.state.session_factory() as db:
        done_row, error_row = db.get(File, ids[0]), db.get(File, ids[1])
        assert (done_row.retranslate_language, done_row.retranslate_engine, done_row.rebuild_font, done_row.language, done_row.font) == (
            "en", "google_free", "serif", "vi", "auto")
        assert (error_row.language, error_row.engine, error_row.font, error_row.retranslate_language) == ("en", "google_free", "serif", None)


@pytest.mark.parametrize(("shared", "code"), [
    ({"language": "zh", "engine": "google_free", "font": "auto"}, "unsupported_language"),
    ({"language": "vi", "engine": "gemini", "font": "auto"}, "missing_api_key"),
    ({"language": "vi", "engine": "google_free", "font": "comic"}, "unsupported_font"),
])
def test_bulk_retranslate_with_bad_settings_queues_nothing(client, me, shared, code):
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "error", 1), ("3.pdf", "queued", 2)])
    response = bulk_retranslate(client, {"ids": ids, "settings": shared})
    assert response.status_code == 400 and response.json() == {"detail": {"code": code}}
    assert statuses(client, ids) == {ids[0]: "done", ids[1]: "error", ids[2]: "queued"}


@pytest.mark.parametrize("body", [
    {}, {"ids": []}, {"ids": ["a"], "all": True}, {"all": False}, {"ids": ["a", "a"]}, {"ids": [f"id{n}" for n in range(101)]},
    {"all": True, "settings": {"language": "vi"}}, {"ids": ["a"], "extra": 1},
    {"all": True, "settings": {"language": "vi", "engine": "google_free", "font": "auto", "extra": 1}},
    {"all": True, "profile": "preset:quick"},
    {"all": True, "settings": {"language": "vi", "engine": "google_free", "font": "auto", "profile": "preset:quick"}},
])
def test_bulk_retranslate_rejects_bad_bodies(client, me, body):
    seed_rows(client, me["id"], [("1.pdf", "done", 0)])
    response = bulk_retranslate(client, body)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "validation"}}
    assert listed(client) == ["1.pdf"]


def test_bulk_retranslate_needs_login_and_csrf_header(client, me):
    seed_rows(client, me["id"], [("1.pdf", "done", 0)])
    forged = client.post("/api/files/bulk-retranslate", json={"all": True}, headers={"X-Requested-With": ""})
    assert forged.status_code == 403 and forged.json() == {"detail": {"code": "csrf"}}
    client.cookies.clear()
    assert bulk_retranslate(client, {"all": True}).status_code == 401


def test_retranslate_skips_a_file_the_runner_takes_first(client, me, monkeypatch):
    """Cập nhật có điều kiện theo trạng thái: luồng chạy / lượt bấm khác đổi trạng thái giữa lúc đọc và lúc ghi."""
    ids = seed_rows(client, me["id"], [("1.pdf", "done", 0), ("2.pdf", "error", 1), ("3.pdf", "done", 2)])
    client.app.state.runner.stop()
    real = service._queue_retranslate

    def racing(db, cfg, row, *choice):
        if row.id != ids[2]:
            with client.app.state.session_factory() as other:
                other.execute(update(File).where(File.id == row.id).values(status="running"))
                other.commit()
        return real(db, cfg, row, *choice)

    monkeypatch.setattr(service, "_queue_retranslate", racing)
    for file_id in ids[:2]:
        response = retranslate(client, file_id, language="en")
        assert response.status_code == 409 and response.json() == {"detail": {"code": "not_retranslatable"}}
    with client.app.state.session_factory() as db:
        db.execute(update(File).where(File.id.in_(ids[:2])).values(status="done"))
        db.commit()
    assert bulk_retranslate(client, {"ids": ids}).json() == {"queued": 1, "skipped_pending": 2, "skipped_limit": 0, "limit": 3}
    with client.app.state.session_factory() as db:
        rows = [db.get(File, file_id) for file_id in ids]
        assert [(row.status, row.retranslate_language, row.rebuild_font) for row in rows] == [
            ("running", None, None), ("running", None, None), ("queued", "vi", "auto")]


def test_bulk_retranslate_loads_no_file_objects(client, me, settings):
    """Quyết định (8) của plan: hàng loạt chỉ chọn cột cần, không nạp File vào session (như xoá hàng loạt)."""
    seed_rows(client, me["id"], [(f"{n}.pdf", "done" if n % 2 else "error", n) for n in range(300)])
    runner = client.app.state.runner
    runner.stop()  # chỉ kiểm phần service
    loaded = []

    def record(target, _context):
        loaded.append(target)

    event.listen(File, "load", record)
    try:
        with client.app.state.session_factory() as db:
            instance_row(db).max_pending_per_user = 100
            db.commit()
            user = db.get(User, me["id"])
            assert service.bulk_retranslate(db, runner, settings, user, ids=None, q="", choice=None) == {
                "queued": 100, "skipped_pending": 0, "skipped_limit": 200, "limit": 100}
    finally:
        event.remove(File, "load", record)
    assert loaded == []
