from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from helpers import FAKE_HANDOFF_WORKER, FAKE_WORKER, MemoryMailer, seed_admin, token_in


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="s" * 32,
        app_base_url="https://app.test",
        data_dir=tmp_path / "data",
        worker_cmd=(sys.executable, str(FAKE_WORKER)),
        handoff_worker_cmd=(sys.executable, str(FAKE_HANDOFF_WORKER)),
        job_stall_seconds=5,
        job_timeout_seconds=30,
    )


@pytest.fixture
def mailer() -> MemoryMailer:
    return MemoryMailer()


@pytest.fixture
def client(settings: Settings, mailer: MemoryMailer):
    app = create_app(settings, mailer=mailer)
    # https: cookie phiên đặt Secure, httpx không gửi cookie Secure qua http.
    with TestClient(app, base_url="https://testserver", headers={"X-Requested-With": "fetch"}) as test_client:
        # Bảng users trống thì register/login đóng (spec 2026-10-05 §2): mỗi test có sẵn một quản trị viên chèn thẳng DB
        # (helpers.ADMIN_EMAIL / ADMIN_PASSWORD, không qua /api/setup, không tốn hạn mức IP). Instance trống: helpers.bare_client(seed=False).
        seed_admin(test_client)
        yield test_client


@pytest.fixture
def sign_up(client: TestClient, mailer: MemoryMailer):
    def _sign_up(email: str = "an@example.com", password: str = "mat-khau-8") -> dict:
        client.cookies.clear()
        assert client.post("/api/auth/register", json={"email": email, "password": password}).status_code == 202
        response = client.post("/api/auth/verify-email", json={"token": token_in(mailer.last_to(email))})
        assert response.status_code == 200, response.text
        return response.json()

    return _sign_up
