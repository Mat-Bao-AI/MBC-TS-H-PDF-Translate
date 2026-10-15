import pytest
from sqlalchemy import delete, func, select

from app.models import TranslationProfile, User
from app.profiles import service
from app.profiles.presets import PRESETS, STYLE_FIELDS
from helpers import PDF, save_key, wait_file

BODY = {"name": "Hợp đồng", "fidelity": "balanced", "tone": "professional", "audience": "client", "terms": "translate_with_original",
        "proper_names": "keep", "numbers": "target_convention", "dates": "target_convention", "abbreviations": "expand",
        "custom_instructions": "Giọng trang trọng, miền Nam."}
PRESET_IDS = ["preset:quick", "preset:client", "preset:technical", "preset:beginner", "preset:academic"]
PRESET_SLUGS = ["quick", "client", "technical", "beginner", "academic"]


@pytest.fixture
def me(sign_up) -> dict:
    return sign_up("an@example.com")


def create(client, **patch):
    return client.post("/api/profiles", json={**BODY, **patch})


def put_preferences(client, **body):
    return client.put("/api/settings/preferences", json={"default_engine": "google_free", **body})


def enable_advanced(client, **body):
    """Bật Chế độ nâng cao như UI thật: động cơ mặc định là AI (spec 2026-10-15 §6 — động cơ thuần làm server tắt chế độ)."""
    save_key(client, "gemini")
    response = client.put("/api/settings/preferences", json={"default_engine": "gemini", "default_model": "gemini-3.5-flash-lite",
                                                             "advance_mode": True, **body})
    assert response.status_code == 200, response.text
    return response.json()


def seeded(client) -> dict[str, dict]:
    """slug → hồ sơ gieo từ mẫu (chỉ dòng có preset_slug)."""
    return {item["preset_slug"]: item for item in client.get("/api/profiles").json() if item.get("preset_slug")}


def upload_with_profile(client, profile):
    return client.post("/api/files", files={"file": ("doc.pdf", PDF, "application/pdf")},
                       data={"language": "vi", "engine": "gemini", "profile": profile})


def test_profiles_need_login(client):
    assert client.get("/api/profiles").status_code == 401
    assert client.post("/api/profiles", json=BODY).status_code == 401


def test_listing_starts_with_the_five_presets_and_settings_carry_them_too(client, me):
    items = client.get("/api/profiles").json()
    assert [item["id"] for item in items] == PRESET_IDS
    assert all(item["kind"] == "preset" and item["created_at"] is None and item["updated_at"] is None for item in items)
    technical = items[2]
    assert technical["name"] == "Tài liệu kỹ thuật" and technical["terms"] == "keep" and technical["audience"] == "expert"
    assert technical["custom_instructions"].startswith("Giữ nguyên tên thư viện")
    settings = client.get("/api/settings").json()
    assert (settings["advance_mode"], settings["default_profile"], settings["profile_limit"]) == (False, None, 20)
    assert settings["profiles"] == items


def test_create_update_delete_a_profile(client, me):
    response = create(client)
    assert response.status_code == 201
    item = response.json()
    assert (item["kind"], item["name"], item["audience"], item["custom_instructions"]) == ("custom", "Hợp đồng", "client", "Giọng trang trọng, miền Nam.")
    assert item["created_at"].endswith("Z") and item["updated_at"] == item["created_at"]
    assert [profile["id"] for profile in client.get("/api/profiles").json()] == [*PRESET_IDS, item["id"]]
    updated = client.put(f"/api/profiles/{item['id']}", json={**BODY, "name": "Hợp đồng B2B", "tone": "friendly"})
    assert updated.status_code == 200 and (updated.json()["name"], updated.json()["tone"]) == ("Hợp đồng B2B", "friendly")
    assert client.delete(f"/api/profiles/{item['id']}").status_code == 204
    assert len(client.get("/api/profiles").json()) == 5
    assert client.delete(f"/api/profiles/{item['id']}").status_code == 404
    assert client.put(f"/api/profiles/{item['id']}", json=BODY).json() == {"detail": {"code": "profile_not_found"}}


def test_enum_fields_default_when_left_out(client, me):
    item = client.post("/api/profiles", json={"name": "Trống"}).json()
    assert {field: item[field] for field in STYLE_FIELDS} == {
        "fidelity": "balanced", "tone": "professional", "audience": "self", "terms": "translate", "proper_names": "keep",
        "numbers": "target_convention", "dates": "target_convention", "abbreviations": "keep", "custom_instructions": ""}


@pytest.mark.parametrize(("patch", "field"), [
    ({"name": ""}, "name"), ({"name": "   "}, "name"), ({"name": "x" * 61}, "name"), ({"name": "a‍b"}, "name"),
    ({"tone": "shouty"}, "tone"), ({"terms": 3}, "terms"), ({"abbreviations": None}, "abbreviations"),
    ({"custom_instructions": "y" * 1001}, "custom_instructions"), ({"custom_instructions": "a\x07b"}, "custom_instructions"),
    ({"custom_instructions": ["x"]}, "custom_instructions"), ({"glossary": []}, "glossary"),
])
def test_invalid_profile_fields_are_refused_with_the_field_name(client, me, patch, field):
    response = create(client, **patch)
    assert response.status_code == 422 and response.json() == {"detail": {"code": "invalid_profile", "field": field}}
    assert len(client.get("/api/profiles").json()) == 5


def test_free_text_is_normalised_but_newlines_survive(client, me):
    item = create(client, name="  Tên  ", custom_instructions="  Dòng 1\r\n\n\n\nDòng 2\t ").json()
    assert (item["name"], item["custom_instructions"]) == ("Tên", "Dòng 1\n\nDòng 2")
    assert create(client, custom_instructions="x" * 999 + "\n\n\n").json()["custom_instructions"] == "x" * 999  # độ dài tính sau chuẩn hoá


def test_twenty_profiles_is_the_limit(client, me):
    for index in range(20):
        assert create(client, name=f"HS {index}").status_code == 201
    response = create(client, name="HS 21")
    assert response.status_code == 409 and response.json() == {"detail": {"code": "too_many_profiles", "limit": 20}}
    assert len(client.get("/api/profiles").json()) == 25


def test_presets_are_read_only(client, me):
    response = client.put("/api/profiles/preset:quick", json=BODY)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "preset_readonly"}}
    assert client.delete("/api/profiles/preset:quick").status_code == 409
    assert client.delete("/api/profiles/preset:nope").status_code == 404
    assert client.get("/api/profiles").json()[0]["name"] == "Đọc nhanh, tự nhiên"


def test_profiles_are_private_to_their_owner(client, sign_up):
    sign_up("an@example.com")
    mine = create(client).json()["id"]
    sign_up("binh@example.com")
    assert len(client.get("/api/profiles").json()) == 5
    assert client.put(f"/api/profiles/{mine}", json=BODY).status_code == 404
    assert client.delete(f"/api/profiles/{mine}").status_code == 404


def test_default_profile_and_advance_mode_are_saved_via_preferences(client, me):
    body = enable_advanced(client, default_profile="preset:technical")
    technical = next(item for item in body["profiles"] if item["preset_slug"] == "technical")
    assert body["default_profile"] == technical["id"]  # bật chế độ: mẫu được gieo thành hồ sơ riêng, tham chiếu preset: → id dòng
    settings = client.get("/api/settings").json()
    assert (settings["advance_mode"], settings["default_profile"]) == (True, technical["id"])
    assert client.get("/api/auth/me").json()["advance_mode"] is True
    assert client.put("/api/settings/preferences", json={"default_engine": "gemini"}).json()["default_profile"] == technical["id"]  # không nhắc tới → giữ
    assert put_preferences(client, default_profile=None).json()["default_profile"] is None
    response = put_preferences(client, default_profile="nope00000000")
    assert response.status_code == 400 and response.json() == {"detail": {"code": "profile_not_found"}}
    assert put_preferences(client, default_profile="preset:nope").status_code == 400
    assert put_preferences(client, default_profile=7).status_code == 400
    mine = create(client).json()["id"]
    assert put_preferences(client, default_profile=mine).json()["default_profile"] == mine
    off = put_preferences(client, advance_mode=False).json()
    assert (off["advance_mode"], off["default_profile"]) == (False, mine)  # tắt chế độ không xoá gì
    assert client.get("/api/auth/me").json()["advance_mode"] is False


def test_a_bad_default_profile_does_not_change_the_engine_either(client, me):
    response = put_preferences(client, default_profile="nope00000000", default_font="serif")
    assert response.status_code == 400
    assert client.get("/api/settings").json()["default_font"] == "auto"  # kiểm hết rồi mới ghi


def test_deleting_the_default_profile_clears_the_default(client, me):
    mine = create(client).json()["id"]
    put_preferences(client, default_profile=mine)
    assert client.delete(f"/api/profiles/{mine}").status_code == 204
    assert client.get("/api/settings").json()["default_profile"] is None
    with client.app.state.session_factory() as db:
        assert db.get(User, me["id"]).default_profile is None


def test_a_default_profile_that_vanished_reads_as_none(client, me):
    mine = create(client).json()["id"]
    put_preferences(client, default_profile=mine)
    with client.app.state.session_factory() as db:  # dòng bị xoá tay / khôi phục DB cũ: tham chiếu treo
        db.execute(delete(TranslationProfile))
        db.commit()
    assert client.get("/api/settings").json()["default_profile"] is None


# ---- Hồ sơ của từng người: gieo mẫu, ánh xạ preset:, khôi phục mẫu gốc (spec 2026-10-15 §5) ------------------------


def test_turning_advanced_mode_on_seeds_the_five_presets_as_my_profiles_once(client, me):
    body = enable_advanced(client, default_profile="preset:technical")
    items = client.get("/api/profiles").json()
    assert [item["preset_slug"] for item in items] == PRESET_SLUGS  # thứ tự mẫu
    assert all(item["kind"] == "custom" and not item["id"].startswith("preset:") and item["created_at"] for item in items)
    technical = items[2]
    assert (technical["name"], technical["terms"], technical["audience"]) == ("Tài liệu kỹ thuật", "keep", "expert")
    assert body["default_profile"] == technical["id"] and body["profiles"] == items
    assert len(enable_advanced(client)["profiles"]) == 5  # lần hai không gieo thêm
    with client.app.state.session_factory() as db:
        assert db.get(User, me["id"]).profiles_seeded is True


def test_seeded_presets_are_ordinary_profiles(client, me):
    enable_advanced(client)
    rows = seeded(client)
    renamed = client.put(f"/api/profiles/{rows['technical']['id']}", json={**BODY, "name": "Kỹ thuật của tôi"}).json()
    assert (renamed["name"], renamed["preset_slug"]) == ("Kỹ thuật của tôi", "technical")  # vẫn "Từ mẫu"
    assert client.delete(f"/api/profiles/{rows['quick']['id']}").status_code == 204
    assert [item["preset_slug"] for item in client.get("/api/profiles").json()] == ["client", "technical", "beginner", "academic"]
    assert put_preferences(client, default_profile=rows["client"]["id"]).json()["default_profile"] == rows["client"]["id"]
    assert client.delete(f"/api/profiles/{rows['client']['id']}").status_code == 204
    assert client.get("/api/settings").json()["default_profile"] is None


def test_preset_references_map_to_the_seeded_rows_and_vanish_with_them(client, me):
    enable_advanced(client)
    rows = seeded(client)
    assert enable_advanced(client, default_profile="preset:quick")["default_profile"] == rows["quick"]["id"]  # chuẩn hoá thành id dòng
    item = upload_with_profile(client, "preset:academic").json()
    assert item["config"]["profile"] == {"id": rows["academic"]["id"], "name": "Học thuật, sát nghĩa", "kind": "custom"}
    assert client.put("/api/profiles/preset:technical", json={**BODY, "name": "Kỹ thuật"}).json()["id"] == rows["technical"]["id"]  # tác động dòng
    assert client.delete("/api/profiles/preset:academic").status_code == 204
    assert "academic" not in seeded(client)
    refused = upload_with_profile(client, "preset:academic")
    assert refused.status_code == 400 and refused.json() == {"detail": {"code": "profile_not_found"}}
    assert put_preferences(client, default_profile="preset:academic").status_code == 400
    assert client.put("/api/profiles/preset:academic", json=BODY).status_code == 404
    assert client.delete("/api/profiles/preset:academic").status_code == 404


def test_retranslating_with_a_deleted_seeded_preset_is_refused(client, me):
    enable_advanced(client)
    rows = seeded(client)
    file_id = upload_with_profile(client, "preset:academic").json()["id"]
    assert wait_file(client, file_id)["status"] == "done"
    assert client.delete(f"/api/profiles/{rows['academic']['id']}").status_code == 204
    response = client.post(f"/api/files/{file_id}/retranslate",
                           json={"language": "vi", "engine": "gemini", "model": None, "font": "auto", "profile": "preset:academic"})
    assert response.status_code == 400 and response.json() == {"detail": {"code": "profile_not_found"}}
    after = client.get(f"/api/files/{file_id}").json()
    assert after["status"] == "done" and after["config"]["profile"]["id"] == rows["academic"]["id"]  # snapshot cũ là bản sao giá trị: giữ nguyên


def test_seeding_stops_at_the_limit_and_restore_presets_fills_the_gap_once_there_is_room(client, me):
    for index in range(17):
        assert create(client, name=f"HS {index}").status_code == 201
    enable_advanced(client)
    items = client.get("/api/profiles").json()
    assert len(items) == 20 and [item["preset_slug"] for item in items[-3:]] == ["quick", "client", "technical"]  # hết chỗ: dừng
    response = client.post("/api/profiles/restore-presets")
    assert response.status_code == 409 and response.json() == {"detail": {"code": "too_many_profiles", "limit": 20}}
    assert len(client.get("/api/profiles").json()) == 20  # không đổi gì
    for item in items[:2]:
        assert client.delete(f"/api/profiles/{item['id']}").status_code == 204
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 3, "created": 2}
    assert sorted(seeded(client)) == sorted(PRESET_SLUGS) and len(client.get("/api/profiles").json()) == 20


def test_restore_presets_on_a_user_never_seeded_checks_room_before_seeding(client, me):
    for index in range(16):
        assert create(client, name=f"HS {index}").status_code == 201
    response = client.post("/api/profiles/restore-presets")  # 16 + 5 > 20: không gieo dở dang
    assert response.status_code == 409 and response.json() == {"detail": {"code": "too_many_profiles", "limit": 20}}
    items = client.get("/api/profiles").json()
    assert [item["id"] for item in items[:5]] == PRESET_IDS and len(items) == 21 and not seeded(client)  # không đổi gì
    with client.app.state.session_factory() as db:
        assert db.get(User, me["id"]).profiles_seeded is False
    assert client.delete(f"/api/profiles/{items[5]['id']}").status_code == 204
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 0, "created": 5}
    settings = client.get("/api/settings").json()
    assert len(settings["profiles"]) == 20 and [item["preset_slug"] for item in settings["profiles"][-5:]] == PRESET_SLUGS


def test_restore_presets_resets_edited_seeded_profiles_and_recreates_deleted_ones(client, me, sign_up):
    enable_advanced(client)
    rows = seeded(client)
    assert client.put(f"/api/profiles/{rows['technical']['id']}", json={**BODY, "name": "Kỹ thuật của tôi", "tone": "friendly"}).status_code == 200
    assert client.delete(f"/api/profiles/{rows['beginner']['id']}").status_code == 204
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 4, "created": 1}
    after = seeded(client)
    assert after["technical"]["id"] == rows["technical"]["id"]  # cùng dòng, giá trị về mẫu
    assert (after["technical"]["name"], after["technical"]["tone"], after["technical"]["terms"]) == ("Tài liệu kỹ thuật", "professional", "keep")
    assert after["beginner"]["id"] != rows["beginner"]["id"] and after["beginner"]["name"] == "Dễ hiểu cho người mới"
    assert len(client.get("/api/profiles").json()) == 5
    sign_up("binh@example.com")  # chưa gieo (chế độ tắt): khôi phục = gieo
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 0, "created": 5}
    assert [item["preset_slug"] for item in client.get("/api/profiles").json()] == PRESET_SLUGS


def test_users_who_already_had_the_mode_on_are_seeded_on_their_next_read(client, me, sign_up):
    def pre_1b(user_id, default_profile):
        with client.app.state.session_factory() as db:  # người dùng đợt 1: chế độ bật, chưa có dòng gieo
            user = db.get(User, user_id)
            user.advance_mode, user.profiles_seeded, user.default_profile = True, False, default_profile
            db.commit()

    pre_1b(me["id"], "preset:client")
    settings = client.get("/api/settings").json()
    assert [item["preset_slug"] for item in settings["profiles"]] == PRESET_SLUGS
    assert settings["default_profile"] == settings["profiles"][1]["id"]  # preset:client → dòng gieo
    binh = sign_up("binh@example.com")
    pre_1b(binh["id"], None)
    assert [item["preset_slug"] for item in client.get("/api/profiles").json()] == PRESET_SLUGS
    chi = sign_up("chi@example.com")  # chưa từng bật: vẫn là mẫu trong code, không có dòng nào
    assert [item["id"] for item in client.get("/api/profiles").json()] == PRESET_IDS
    with client.app.state.session_factory() as db:
        assert db.get(User, chi["id"]).profiles_seeded is False


def test_two_requests_racing_to_seed_create_the_five_rows_once(client, me):
    factory = client.app.state.session_factory
    with factory() as late, factory() as later:
        stale, stale_too = late.get(User, me["id"]), later.get(User, me["id"])  # hai request đọc cờ = 0 trước khi request khác gieo
        with factory() as first:
            assert service.seed_presets(first, first.get(User, me["id"])) is True
        assert service.seed_presets(late, stale) is False and stale.profiles_seeded is True  # UPDATE có điều kiện: thua thì thôi
        assert service.restore_presets(later, stale_too) == {"updated": 5, "created": 0}  # khôi phục thua lượt gieo: khôi phục như đã gieo
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TranslationProfile)) == 5


def test_a_failed_seed_does_not_break_reading_the_settings(client, me, monkeypatch):
    with client.app.state.session_factory() as db:
        db.get(User, me["id"]).advance_mode = True
        db.commit()

    def boom(db, user):  # hỏng SAU khi UPDATE giành cờ đã chạy: rollback phải trả cờ về 0
        raise RuntimeError("database is locked")

    monkeypatch.setattr("app.profiles.service._count", boom)
    response = client.get("/api/settings")
    assert response.status_code == 200 and [item["id"] for item in response.json()["profiles"]] == PRESET_IDS  # như chưa gieo
    profiles = client.get("/api/profiles")
    assert profiles.status_code == 200 and [item["id"] for item in profiles.json()] == PRESET_IDS
    with client.app.state.session_factory() as db:
        assert db.get(User, me["id"]).profiles_seeded is False
        assert db.scalar(select(func.count()).select_from(TranslationProfile)) == 0


def test_restore_presets_that_loses_a_race_resets_the_row_the_other_request_created(client, me, monkeypatch):
    enable_advanced(client)
    rows = seeded(client)
    assert client.delete(f"/api/profiles/{rows['beginner']['id']}").status_code == 204
    real_count, raced = service._count, []

    def count_then_lose_the_race(db, user):  # request khôi phục khác chèn dòng beginner và commit giữa lượt đọc và commit của request này
        if not raced:
            raced.append(True)
            with client.app.state.session_factory() as other:
                other.add(TranslationProfile(id="competitor01", user_id=user.id, preset_slug="beginner",
                                             **{**PRESETS["beginner"], "name": "Bản của request kia"}))
                other.commit()
        return real_count(db, user)

    monkeypatch.setattr("app.profiles.service._count", count_then_lose_the_race)
    response = client.post("/api/profiles/restore-presets")
    assert response.status_code == 200 and response.json() == {"updated": 5, "created": 0}  # lượt hai: dòng của request kia được đặt lại
    items = client.get("/api/profiles").json()
    assert sorted(item["preset_slug"] for item in items) == sorted(PRESET_SLUGS) and len(items) == 5  # mỗi mẫu đúng một dòng
    assert (seeded(client)["beginner"]["id"], seeded(client)["beginner"]["name"]) == ("competitor01", "Dễ hiểu cho người mới")


def test_restore_presets_points_a_leftover_preset_default_at_its_row(client, me):
    for index in range(17):
        assert create(client, name=f"HS {index}").status_code == 201
    customs = [item["id"] for item in client.get("/api/profiles").json() if item["kind"] == "custom"]
    assert enable_advanced(client, default_profile="preset:academic")["default_profile"] is None  # gieo dừng ở 3 mẫu: academic chưa có dòng

    def stored_default():
        with client.app.state.session_factory() as db:
            return db.get(User, me["id"]).default_profile

    assert stored_default() == "preset:academic"  # chuỗi thô còn lại
    for profile_id in customs[:2]:
        assert client.delete(f"/api/profiles/{profile_id}").status_code == 204
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 3, "created": 2}
    academic = seeded(client)["academic"]["id"]
    assert client.get("/api/settings").json()["default_profile"] == academic and stored_default() == academic  # chuẩn hoá như seed_presets
    assert client.delete(f"/api/profiles/{academic}").status_code == 204
    assert stored_default() is None  # xoá hồ sơ mặc định thì bỏ mặc định
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 4, "created": 1}
    assert client.get("/api/settings").json()["default_profile"] is None  # khôi phục không dựng lại mặc định đã bỏ


def test_seeded_profiles_stay_private_to_their_owner(client, me, sign_up):
    enable_advanced(client)
    mine = list(seeded(client).values())

    def an_rows():
        with client.app.state.session_factory() as db:
            return [service.profile_item(row) for row in db.scalars(select(TranslationProfile).where(TranslationProfile.user_id == me["id"])
                                                                     .order_by(TranslationProfile.created_at, TranslationProfile.id))]

    assert an_rows() == mine
    sign_up("binh@example.com")
    enable_advanced(client)
    binh = seeded(client)
    assert not {item["id"] for item in mine} & {item["id"] for item in binh.values()}
    for item in mine:
        assert client.put(f"/api/profiles/{item['id']}", json=BODY).status_code == 404
        assert client.delete(f"/api/profiles/{item['id']}").status_code == 404
    assert put_preferences(client, default_profile=mine[0]["id"]).status_code == 400
    assert upload_with_profile(client, mine[0]["id"]).status_code == 400
    assert client.put("/api/profiles/preset:technical", json={**BODY, "name": "Của Bình"}).json()["id"] == binh["technical"]["id"]
    assert client.delete("/api/profiles/preset:quick").status_code == 204
    assert upload_with_profile(client, "preset:academic").json()["config"]["profile"]["id"] == binh["academic"]["id"]
    assert put_preferences(client, default_profile="preset:client").json()["default_profile"] == binh["client"]["id"]
    assert client.post("/api/profiles/restore-presets").json() == {"updated": 4, "created": 1}
    assert an_rows() == mine  # hồ sơ gieo của An không đổi
