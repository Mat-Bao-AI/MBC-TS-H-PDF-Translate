import pytest

from app.config import DEFAULT_HANDOFF_WORKER_CMD, DEFAULT_WORKER_CMD, ConfigError, load_settings, normalize_base_url

BASE = {"SECRET_KEY": "k" * 32, "APP_BASE_URL": "https://pdf.example.com/"}


def test_minimal_env_uses_defaults():
    s = load_settings(BASE)
    assert s.app_base_url == "https://pdf.example.com"
    assert str(s.data_dir) == "/data"
    assert (s.max_upload_mb, s.max_concurrent_jobs, s.max_pending_per_user) == (50, 1, 3)
    assert (s.job_stall_seconds, s.job_timeout_seconds) == (480, 10800)
    assert s.default_target_lang == "vi"
    assert s.worker_cmd == DEFAULT_WORKER_CMD
    assert s.worker_cmd[1].endswith("app/engine/font_worker.py")
    assert s.handoff_worker_cmd == DEFAULT_HANDOFF_WORKER_CMD
    assert s.handoff_worker_cmd[1].endswith("app/engine/handoff_worker.py")
    assert s.static_dir is None
    assert s.database_url == "sqlite:////data/app.db"


def test_setup_token_and_mail_dev_log_are_parsed():
    s = load_settings(BASE)
    assert (s.setup_token, s.mail_dev_log) == ("", False)
    s = load_settings({**BASE, "SETUP_TOKEN": "  bi-mat-cai-dat ", "MAIL_DEV_LOG": "1"})
    assert (s.setup_token, s.mail_dev_log) == ("bi-mat-cai-dat", True)
    assert load_settings({**BASE, "MAIL_DEV_LOG": "0"}).mail_dev_log is False


@pytest.mark.parametrize("secret", ["", "short"])
def test_secret_key_is_required(secret):
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        load_settings({**BASE, "SECRET_KEY": secret})


def test_base_url_must_be_absolute():
    with pytest.raises(ConfigError, match="APP_BASE_URL"):
        load_settings({**BASE, "APP_BASE_URL": "pdf.example.com"})


@pytest.mark.parametrize("env", [{}, {"APP_BASE_URL": ""}, {"APP_BASE_URL": "   "}])
def test_base_url_is_optional(env):
    # Không đặt (hoặc compose chuyển tiếp `${APP_BASE_URL:-}` rỗng): địa chỉ trang lấy từ lúc chạy /setup (system.store.site_url).
    assert load_settings({"SECRET_KEY": "k" * 32, **env}).app_base_url is None


ABSOLUTE = "APP_BASE_URL phải là địa chỉ đầy đủ, ví dụ https://pdf.example.com"
HTTPS_ONLY = "APP_BASE_URL phải dùng https:// (http:// chỉ cho localhost / 127.0.0.1)"


@pytest.mark.parametrize(("raw", "message"), [
    ("pdf.example.com", ABSOLUTE), ("/", ABSOLUTE), ("ftp://pdf.example.com", ABSOLUTE), ("http://[::1", ABSOLUTE),
    ("http://pdf.example.com", HTTPS_ONLY), ("http://localhost.evil.com/", HTTPS_ONLY),
])
def test_invalid_base_urls_keep_their_messages(raw, message):
    # MỘT hàm kiểm cho cả env lẫn địa chỉ ghi lúc /setup: cùng thông điệp ở cả hai đường.
    for check in (normalize_base_url, lambda value: load_settings({**BASE, "APP_BASE_URL": value})):
        with pytest.raises(ConfigError) as refused:
            check(raw)
        assert str(refused.value) == message


def test_normalize_base_url_trims_and_strips_the_trailing_slash():
    assert normalize_base_url("  https://pdf.example.com/ ") == "https://pdf.example.com"
    assert normalize_base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"


def test_smtp_host_requires_sender():
    with pytest.raises(ConfigError, match="SMTP_FROM"):
        load_settings({**BASE, "SMTP_HOST": "smtp.example.com"})


def test_smtp_security_is_parsed_and_legacy_starttls_0_means_none():
    assert load_settings(BASE).smtp_security == "starttls"
    assert load_settings({**BASE, "SMTP_SECURITY": " SSL "}).smtp_security == "ssl"
    assert load_settings({**BASE, "SMTP_STARTTLS": "0"}).smtp_security == "none"
    assert load_settings({**BASE, "SMTP_STARTTLS": "0", "SMTP_SECURITY": "starttls"}).smtp_security == "starttls"  # SMTP_SECURITY thắng


def test_unknown_smtp_security_is_rejected():
    with pytest.raises(ConfigError, match="SMTP_SECURITY"):
        load_settings({**BASE, "SMTP_SECURITY": "tls"})


def test_ssl_defaults_to_port_465_unless_smtp_port_is_set():
    assert load_settings(BASE).smtp_port == 587
    assert load_settings({**BASE, "SMTP_SECURITY": "ssl"}).smtp_port == 465
    assert load_settings({**BASE, "SMTP_SECURITY": "ssl", "SMTP_PORT": "2465"}).smtp_port == 2465
    assert load_settings({**BASE, "SMTP_SECURITY": "none"}).smtp_port == 587


def test_empty_strings_from_compose_mean_unset():
    """docker-compose.yml chuyển tiếp `${BIEN:-}` → biến có mặt nhưng rỗng: phải như không đặt (ssl vẫn về 465)."""
    blank = {name: "" for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_SECURITY",
                                   "MAIL_DEV_LOG", "SETUP_TOKEN", "SOURCE_URL")}
    s = load_settings({**BASE, **blank})
    assert (s.smtp_host, s.smtp_port, s.smtp_security, s.mail_dev_log, s.setup_token) == ("", 587, "starttls", False, "")
    assert load_settings({**BASE, **blank, "SMTP_SECURITY": "ssl"}).smtp_port == 465


def test_printing_settings_never_shows_secrets():
    s = load_settings({**BASE, "SMTP_HOST": "smtp.example.com", "SMTP_FROM": "no-reply@example.com",
                       "SMTP_PASSWORD": "mat-khau-smtp-env", "SETUP_TOKEN": "bi-mat-cai-dat"})
    shown = repr(s)
    assert "k" * 32 not in shown and "mat-khau-smtp-env" not in shown and "bi-mat-cai-dat" not in shown
    assert "smtp.example.com" in shown  # phần còn lại vẫn in ra để chẩn đoán
    assert (s.secret_key, s.smtp_password, s.setup_token) == ("k" * 32, "mat-khau-smtp-env", "bi-mat-cai-dat")


def test_non_numeric_limit_is_rejected():
    with pytest.raises(ConfigError, match="MAX_UPLOAD_MB"):
        load_settings({**BASE, "MAX_UPLOAD_MB": "lots"})


def test_source_url_must_be_https():
    assert load_settings({**BASE, "SOURCE_URL": "https://git.example.com/x/pdf-translate"}).source_url.endswith("pdf-translate")
    assert load_settings(BASE).source_url == ""
    with pytest.raises(ConfigError, match="SOURCE_URL"):
        load_settings({**BASE, "SOURCE_URL": "javascript:alert(1)"})


def test_overrides_are_parsed():
    s = load_settings({
        **BASE,
        "WORKER_CMD": "python tests/fake_worker.py",
        "HANDOFF_WORKER_CMD": "python tests/fake_handoff_worker.py",
        "JOB_STALL_MINUTES": "2",
        "MAX_UPLOAD_MB": "10",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_FROM": "PDF Translate <no-reply@example.com>",
        "SMTP_STARTTLS": "false",
        "STATIC_DIR": "/app/static",
        "DATA_DIR": "/tmp/d",
    })
    assert s.worker_cmd == ("python", "tests/fake_worker.py")
    assert s.handoff_worker_cmd == ("python", "tests/fake_handoff_worker.py")
    assert s.job_stall_seconds == 120 and s.max_upload_mb == 10
    assert s.smtp_security == "none" and s.smtp_port == 587
    assert str(s.static_dir) == "/app/static"
    assert s.database_url == "sqlite:////tmp/d/app.db"


@pytest.mark.parametrize("url", [
    "http://pdf.example.com", "http://10.0.0.5:8000", "http://localhost.evil.com", "http://pdf.ts.dev.example.com",
])
def test_plain_http_base_url_only_for_localhost(url):
    # Cookie phiên đặt Secure: qua http thường trình duyệt bỏ cookie → đăng nhập xong lại bị đá ra.
    with pytest.raises(ConfigError, match="APP_BASE_URL"):
        load_settings({**BASE, "APP_BASE_URL": url})


@pytest.mark.parametrize("url", ["http://localhost", "http://localhost:18081", "http://127.0.0.1:8000"])
def test_plain_http_base_url_is_fine_on_localhost(url):
    assert load_settings({**BASE, "APP_BASE_URL": url}).app_base_url == url
