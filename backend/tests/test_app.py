from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import MIGRATIONS, upgrade_db
from app.models import Base


def test_health_is_public(client):
    response = client.get("/health", headers={"X-Requested-With": ""})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "queue": 0}


def test_migrations_create_every_table(client, settings):
    engine = create_engine(settings.database_url)
    assert {"users", "sessions", "email_tokens", "files", "api_credentials"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migrations_match_models(client, settings):
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def test_upgrade_from_0001_keeps_existing_tokens(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, password_hash, created_at) "
                                "VALUES ('u1', 'a@example.com', 'x', '2026-10-01 00:00:00')"))
        connection.execute(text("INSERT INTO email_tokens (token_hash, user_id, kind, expires_at) "
                                "VALUES ('h1', 'u1', 'verify', '2026-10-02 00:00:00')"))
    upgrade_db(url)
    assert "nonce_hash" in {column["name"] for column in inspect(engine).get_columns("email_tokens")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT token_hash, nonce_hash FROM email_tokens")).all() == [("h1", None)]
    engine.dispose()


def test_upgrade_from_0002_backfills_engine_columns(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0002")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, password_hash, created_at) "
                                "VALUES ('u1', 'a@example.com', 'x', '2026-10-01 00:00:00')"))
        connection.execute(text(
            "INSERT INTO files (id, user_id, filename, search_name, language, status, done_pages, total_pages, "
            "untranslated, message, created_at) VALUES ('f1', 'u1', 'a.pdf', 'a.pdf', 'vi', 'done', 2, 2, 0, 'Xong', "
            "'2026-10-01 00:00:00')"))
    upgrade_db(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT default_engine, default_model FROM users")).all() == [("google_free", None)]
        assert connection.execute(text("SELECT engine, model, stage FROM files")).all() == [("google_free", None, "")]
        assert connection.execute(text("SELECT COUNT(*) FROM api_credentials")).scalar() == 0
    engine.dispose()


def _upgrade_to(url: str, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, revision)


def _seed_0003(url: str):
    _upgrade_to(url, "0003")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email, password_hash, created_at, default_engine) "
                                "VALUES ('u1', 'a@example.com', 'x', '2026-10-01 00:00:00', 'google_free')"))
        connection.execute(text(
            "INSERT INTO files (id, user_id, filename, search_name, language, status, done_pages, total_pages, "
            "untranslated, message, output_name, created_at, engine, stage) VALUES ('f1', 'u1', 'a.pdf', 'a.pdf', 'vi', "
            "'done', 2, 2, 0, 'Xong', 'a-vi.pdf', '2026-10-01 00:00:00', 'google_free', '')"))
        connection.execute(text("INSERT INTO email_tokens (token_hash, user_id, kind, expires_at) "
                                "VALUES ('h1', 'u1', 'reset', '2026-10-02 00:00:00')"))
    return engine


def test_upgrade_from_0003_backfills_account_and_font_columns(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    engine = _seed_0003(url)
    upgrade_db(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT display_name, default_font FROM users")).all() == [(None, "auto")]
        assert connection.execute(text("SELECT font, font_used, rebuild_font, rebuild_error, output_name FROM files")).all() == [
            ("auto", None, None, "", "a-vi.pdf")]
        assert connection.execute(text("SELECT kind, new_email FROM email_tokens")).all() == [("reset", None)]
    engine.dispose()


def test_downgrade_from_0004_keeps_existing_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    engine = _seed_0003(url)
    upgrade_db(url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "0003")
    assert "font" not in {column["name"] for column in inspect(engine).get_columns("files")}
    assert "display_name" not in {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, email FROM users")).all() == [("u1", "a@example.com")]
        assert connection.execute(text("SELECT id, status, output_name FROM files")).all() == [("f1", "done", "a-vi.pdf")]
        assert connection.execute(text("SELECT token_hash FROM email_tokens")).all() == [("h1",)]
    engine.dispose()


def _seed_0004(url: str):
    _upgrade_to(url, "0004")
    engine = create_engine(url)
    with engine.begin() as connection:
        # Chèn người MỚI trước người CŨ: admin phải chọn theo created_at, không theo thứ tự chèn hay id.
        connection.execute(text("INSERT INTO users (id, email, password_hash, created_at, default_engine) "
                                "VALUES ('u2', 'moi@example.com', 'x', '2026-10-03 00:00:00', 'google_free')"))
        connection.execute(text("INSERT INTO users (id, email, password_hash, created_at, default_engine) "
                                "VALUES ('u1', 'cu@example.com', 'x', '2026-10-01 00:00:00', 'google_free')"))
        connection.execute(text(
            "INSERT INTO files (id, user_id, filename, search_name, language, status, done_pages, total_pages, "
            "untranslated, message, output_name, created_at, engine, stage) VALUES ('f1', 'u1', 'a.pdf', 'a.pdf', 'vi', "
            "'done', 2, 2, 0, 'Xong', 'a-vi.pdf', '2026-10-01 00:00:00', 'google_free', '')"))
    return engine


def test_upgrade_from_0004_makes_the_oldest_user_admin_and_seeds_instance_settings(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    engine = _seed_0004(url)
    upgrade_db(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, is_admin FROM users ORDER BY id")).all() == [("u1", 1), ("u2", 0)]
        rows = connection.execute(text(
            "SELECT id, smtp_host, registration_open, max_pending_per_user, setup_completed_at FROM instance_settings")).all()
        assert len(rows) == 1 and rows[0][:4] == (1, None, 1, None) and rows[0][4] is not None  # đã có user = đã cài đặt
        assert connection.execute(text("SELECT retranslate_language, retranslate_engine, retranslate_model FROM files")).all() == [
            (None, None, None)]
    engine.dispose()


def test_upgrade_from_0004_breaks_a_created_at_tie_by_the_smallest_id(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    _upgrade_to(url, "0004")
    engine = create_engine(url)
    with engine.begin() as connection:
        # 'b' chèn trước 'a', cùng created_at (dạng ORM, có micro giây): hoà thì id nhỏ nhất thắng, không theo thứ tự chèn.
        for user_id, created_at in (("b", "2026-10-01 09:00:00.123456"), ("a", "2026-10-01 09:00:00.123456"),
                                    ("c", "2026-10-02 09:00:00.000000")):
            connection.execute(text("INSERT INTO users (id, email, password_hash, created_at, default_engine) "
                                    "VALUES (:id, :email, 'x', :created_at, 'google_free')"),
                               {"id": user_id, "email": f"{user_id}@example.com", "created_at": created_at})
    upgrade_db(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, is_admin FROM users ORDER BY id")).all() == [("a", 1), ("b", 0), ("c", 0)]
    engine.dispose()


def test_downgrade_from_0005_keeps_existing_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    engine = _seed_0004(url)
    upgrade_db(url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "0004")
    assert "instance_settings" not in inspect(engine).get_table_names()
    assert "is_admin" not in {column["name"] for column in inspect(engine).get_columns("users")}
    assert "retranslate_language" not in {column["name"] for column in inspect(engine).get_columns("files")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users ORDER BY id")).all() == [("u1",), ("u2",)]
        assert connection.execute(text("SELECT id, status, output_name FROM files")).all() == [("f1", "done", "a-vi.pdf")]
    engine.dispose()


def test_upgrade_from_0005_defaults_the_smtp_notice_to_not_dismissed_and_downgrade_keeps_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    engine = _seed_0004(url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0005")
    assert "smtp_notice_dismissed" not in {column["name"] for column in inspect(engine).get_columns("users")}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, smtp_notice_dismissed FROM users ORDER BY id")).all() == [("u1", 0), ("u2", 0)]
    command.downgrade(config, "0005")
    assert "smtp_notice_dismissed" not in {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, is_admin FROM users ORDER BY id")).all() == [("u1", 1), ("u2", 0)]
    engine.dispose()


def test_upgrade_from_0006_adds_an_unknown_site_url_and_downgrade_keeps_the_settings_row(tmp_path):
    url = f"sqlite:///{tmp_path / 'cu.db'}"
    engine = _seed_0004(url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0006")
    assert "site_url" not in {column["name"] for column in inspect(engine).get_columns("instance_settings")}
    with engine.begin() as connection:
        connection.execute(text("UPDATE instance_settings SET registration_open = 0, max_pending_per_user = 7"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        # Instance nâng cấp: chưa ghi địa chỉ (cài từ trước, khi APP_BASE_URL còn bắt buộc) — giá trị khác giữ nguyên.
        assert connection.execute(text(
            "SELECT id, registration_open, max_pending_per_user, site_url FROM instance_settings")).all() == [(1, 0, 7, None)]
    command.downgrade(config, "0006")
    assert "site_url" not in {column["name"] for column in inspect(engine).get_columns("instance_settings")}
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT id, registration_open, max_pending_per_user FROM instance_settings")).all() == [(1, 0, 7)]
    with pytest.raises(IntegrityError), engine.begin() as connection:  # CHECK id = 1 còn sau khi batch dựng lại bảng
        connection.execute(text("INSERT INTO instance_settings (id, registration_open, updated_at) "
                                "VALUES (2, 1, CURRENT_TIMESTAMP)"))
    engine.dispose()


def test_a_fresh_database_has_the_settings_row_without_setup_completed(client, settings):
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT id, registration_open, max_pending_per_user, setup_completed_at FROM instance_settings")).all() == [(1, 1, None, None)]
    engine.dispose()


def test_unsafe_api_request_without_fetch_header_is_rejected(client):
    response = client.post("/api/anything", headers={"X-Requested-With": ""})
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "csrf"}}


def test_validation_error_has_the_standard_shape(client):
    response = client.post("/api/auth/login", json={})
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "validation"}}


def test_malformed_json_body_has_the_standard_shape(client):
    response = client.post("/api/auth/login", content="{", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "validation"}}


def test_unknown_route_has_the_standard_shape(client):
    response = client.get("/api/khong-co")
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "not_found"}}


def test_wrong_method_has_the_standard_shape(client):
    response = client.get("/api/auth/logout")
    assert response.status_code == 405
    assert response.json() == {"detail": {"code": "method_not_allowed"}}
