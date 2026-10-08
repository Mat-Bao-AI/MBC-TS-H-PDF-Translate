import importlib
import mimetypes
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.spa
from app.main import create_app


@pytest.fixture
def spa_client(settings, mailer, tmp_path):
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>PDF Translate</title>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("bi-mat", encoding="utf-8")
    app = create_app(replace(settings, static_dir=root), mailer=mailer)
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def test_app_routes_fall_back_to_index(spa_client):
    for path in ("/", "/login", "/files/abc123"):
        response = spa_client.get(path)
        assert response.status_code == 200 and "PDF Translate" in response.text
        assert response.headers["cache-control"] == "no-cache"


def test_assets_are_served(spa_client):
    response = spa_client.get("/assets/app.js")
    assert response.status_code == 200 and response.text == "console.log(1)"


def test_static_files_cannot_escape_their_folder(spa_client):
    assert "bi-mat" not in spa_client.get("/..%2Fsecret.txt").text


def test_unknown_api_path_is_a_json_404(spa_client):
    response = spa_client.get("/api/khong-co")
    assert response.status_code == 404 and response.json() == {"detail": {"code": "not_found"}}


def test_health_and_api_still_win(spa_client):
    assert spa_client.get("/health").json()["status"] == "ok"
    assert spa_client.get("/api/auth/me").status_code == 401


def test_missing_asset_is_a_404_not_the_app_shell(spa_client):
    # Bản build cũ trong cache trình duyệt xin chunk đã đổi tên: trả index.html (200, text/html) cho
    # một URL .js làm trình duyệt báo lỗi MIME khó hiểu; 404 rõ ràng hơn.
    for path in ("/assets/khong-co.js", "/assets"):
        response = spa_client.get(path)
        assert response.status_code == 404, path
        assert "PDF Translate" not in response.text


def test_self_hosted_fonts_get_a_font_content_type(settings, mailer, tmp_path, monkeypatch):
    # python:3.12-slim không có /etc/mime.types: dựng lại bảng MIME rỗng để test không phụ thuộc máy chạy.
    monkeypatch.setattr(mimetypes, "knownfiles", [])
    monkeypatch.setattr(mimetypes, "inited", False)
    monkeypatch.setattr(mimetypes, "_db", None)
    mimetypes.init(files=[])
    assert mimetypes.guess_type("x.woff2")[0] is None
    importlib.reload(app.spa)  # đăng ký lại các add_type ở mức module
    assert mimetypes.guess_type("x.woff2")[0] == "font/woff2" and mimetypes.guess_type("x.woff")[0] == "font/woff"
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "assets" / "inter.woff2").write_bytes(b"wOF2\x00\x01\x00\x00")
    (root / "assets" / "inter.woff").write_bytes(b"wOFF\x00\x01\x00\x00")
    with TestClient(create_app(replace(settings, static_dir=root), mailer=mailer), base_url="https://testserver") as client:
        for name, kind in (("inter.woff2", "font/woff2"), ("inter.woff", "font/woff")):
            response = client.get(f"/assets/{name}")
            assert response.status_code == 200 and response.headers["content-type"] == kind, name
