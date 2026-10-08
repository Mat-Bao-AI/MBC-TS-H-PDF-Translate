from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth.account_router import router as account_router
from .auth.mailer import Mailer
from .auth.ratelimit import SlidingWindow
from .auth.router import router as auth_router
from .auth.service import AuthService
from .config import Settings, load_settings
from .db import make_engine, make_session_factory, upgrade_db
from .deps import require_fetch_header
from .engine.jobs import JobRunner
from .errors import ApiError, api_error_handler, http_exception_handler, validation_error_handler
from .files.router import router as files_router
from .limits import BodyLimitMiddleware
from .providers.client import RequestsTransport
from .providers.router import router as settings_router
from .spa import mount_spa
from .system.router import router as system_router
from .system.setup_router import router as setup_router


def create_app(settings: Settings | None = None, mailer: Mailer | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.users_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    runner = JobRunner.from_settings(settings, session_factory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        upgrade_db(settings.database_url)
        runner.start()
        yield
        runner.stop()
        engine.dispose()

    app = FastAPI(title="PDF Translate", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.runner = runner
    app.state.injected_mailer = mailer  # test tiêm; None = giải theo DB → env → MAIL_DEV_LOG → log lúc gửi (app.system.mail)
    app.state.auth = AuthService(settings)
    app.state.test_mail_throttle = SlidingWindow(limit=6, window_seconds=60)  # thư thử: 6 lượt/phút/admin
    # Lưu key = một request thật tới Google bằng key người dán: không giới hạn thì thành máy dò key bị lộ hàng loạt.
    app.state.credential_user_throttle = SlidingWindow(limit=10, window_seconds=900)  # 10 lượt / 15 phút / tài khoản
    app.state.credential_ip_throttle = SlidingWindow(limit=20, window_seconds=900)  # 20 lượt / 15 phút / IP
    app.state.provider_transport = RequestsTransport()  # test thay bằng FakeTransport
    app.middleware("http")(require_fetch_header)
    # Thêm sau = bọc ngoài: giới hạn thân + kiểm phiên cho upload chạy trước CSRF và trước routing.
    app.add_middleware(BodyLimitMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "queue": runner.queue_depth()}

    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(files_router)
    app.include_router(settings_router)
    app.include_router(system_router)
    app.include_router(setup_router)
    if settings.static_dir is not None:
        mount_spa(app, settings.static_dir)
    return app
