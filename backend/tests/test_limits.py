"""Giới hạn thân request (app/limits.py): chặn TRƯỚC khi FastAPI đọc/spool thân."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.limits import BodyLimitMiddleware
from helpers import PDF, upload

JSON = {"Content-Type": "application/json"}
MULTIPART = {"Content-Type": "multipart/form-data; boundary=ranh-gioi"}


def tracked(payload: bytes, consumed: list):
    """Thân dạng generator: httpx gửi chunked (không Content-Length); ghi lại nếu app có đọc."""
    def body():
        consumed.append(True)
        yield payload
    return body()


@pytest.fixture
def me(sign_up) -> dict:
    return sign_up("an@example.com")


def test_json_body_declared_over_64k_is_refused_unread(client):
    consumed: list = []
    response = client.post("/api/auth/login", content=tracked(b"{}", consumed),
                           headers={**JSON, "Content-Length": str(64 * 1024 + 1)})
    assert response.status_code == 413 and response.json() == {"detail": {"code": "request_too_large"}}
    assert consumed == []


def test_streamed_json_body_over_64k_is_cut_off(client):
    payload = b'{"email": "' + b"a" * (64 * 1024) + b'", "password": "x"}'
    response = client.post("/api/auth/login", content=tracked(payload, []), headers=JSON)
    assert response.status_code == 413 and response.json() == {"detail": {"code": "request_too_large"}}


def test_small_json_bodies_still_work(client):
    response = client.post("/api/auth/login", json={"email": "ai@example.com", "password": "mat-khau-8"})
    assert response.status_code == 401 and response.json() == {"detail": {"code": "invalid_credentials"}}


def test_anonymous_upload_is_refused_before_the_body_is_read(client):
    consumed: list = []
    response = client.post("/api/files", content=tracked(b"x" * (2 * 1024 * 1024), consumed), headers=MULTIPART)
    assert response.status_code == 401 and response.json() == {"detail": {"code": "unauthenticated"}}
    assert consumed == []


def test_upload_with_a_dead_session_is_refused_before_the_body_is_read(client):
    consumed: list = []
    response = client.post("/api/files", content=tracked(b"x" * 1024, consumed),
                           headers={**MULTIPART, "Cookie": "session=khong-ton-tai"})
    assert response.status_code == 401 and response.json() == {"detail": {"code": "unauthenticated"}}
    assert consumed == []


def test_upload_declared_over_the_limit_is_refused_unread(client, me, settings):
    client.app.state.settings = replace(client.app.state.settings, max_upload_mb=1)
    consumed: list = []
    declared = 1024 * 1024 + 64 * 1024 + 1
    response = client.post("/api/files", content=tracked(b"x", consumed),
                           headers={**MULTIPART, "Content-Length": str(declared)})
    assert response.status_code == 413 and response.json() == {"detail": {"code": "too_large", "mb": 1}}
    assert consumed == []
    assert list(settings.users_dir.rglob("*.pdf")) == []


def test_upload_just_over_the_file_limit_still_gets_the_precise_error(client, me, settings):
    # Thân nằm dưới trần của middleware (MB + 64KB) nhưng tệp > MB: service vẫn báo too_large + dọn dẹp.
    client.app.state.settings = replace(client.app.state.settings, max_upload_mb=1)
    response = upload(client, "big.pdf", PDF + b"0" * (1024 * 1024))
    assert response.status_code == 413 and response.json() == {"detail": {"code": "too_large", "mb": 1}}
    assert list(settings.users_dir.rglob("*.pdf")) == []


def test_normal_upload_passes_the_limits(client, me):
    assert upload(client, "doc.pdf").status_code == 202


def test_csrf_check_still_applies_to_signed_in_uploads(client, me):
    response = client.post("/api/files", files={"file": ("doc.pdf", PDF, "application/pdf")},
                           data={"language": "vi"}, headers={"X-Requested-With": ""})
    assert response.status_code == 403 and response.json() == {"detail": {"code": "csrf"}}


def test_csrf_check_still_applies_to_small_json_posts(client):
    response = client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"}, headers={"X-Requested-With": ""})
    assert response.status_code == 403 and response.json() == {"detail": {"code": "csrf"}}


# ---- Mức ASGI: thân chia nhiều mảnh, client nói dối Content-Length ---------------------------

def run_asgi(app, chunks: list[bytes], headers: list[tuple[bytes, bytes]] = (), path: str = "/api/auth/login"):
    scope = {"type": "http", "method": "POST", "path": path, "headers": list(headers),
             "app": SimpleNamespace(state=SimpleNamespace())}
    pending = [{"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
               for index, chunk in enumerate(chunks)]
    pulled: list[int] = []
    sent: list[dict] = []

    async def receive():
        if not pending:
            return {"type": "http.disconnect"}
        pulled.append(1)
        return pending.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(BodyLimitMiddleware(app)(scope, receive, send))
    return pulled, sent


def test_chunked_body_is_counted_across_chunks_and_reading_stops():
    seen: list[dict] = []

    async def app(scope, receive, send):
        while True:
            message = await receive()
            seen.append(message)
            if message["type"] == "http.disconnect" or not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunks = [b"a" * (30 * 1024)] * 5  # 150KB, không khai Content-Length
    pulled, sent = run_asgi(app, chunks)
    assert len(pulled) == 3  # mảnh thứ 3 làm vượt 64KB → không kéo thêm mảnh nào
    assert seen[-1] == {"type": "http.disconnect"}
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 413
    assert b"request_too_large" in sent[1]["body"]
    assert len(sent) == 2  # phản hồi muộn của app bị nuốt


def test_lying_content_length_is_still_counted():
    async def app(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    _, sent = run_asgi(app, [b"a" * (40 * 1024)] * 2, headers=[(b"content-length", b"10")])
    assert sent[0]["status"] == 413


def test_after_the_response_started_it_only_stops_reading():
    seen: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            message = await receive()
            seen.append(message)
            if message["type"] == "http.disconnect" or not message.get("more_body"):
                break
        await send({"type": "http.response.body", "body": b"ok"})

    _, sent = run_asgi(app, [b"a" * (40 * 1024)] * 3)
    assert seen[-1] == {"type": "http.disconnect"}
    assert [message.get("status") for message in sent if message["type"] == "http.response.start"] == [200]
