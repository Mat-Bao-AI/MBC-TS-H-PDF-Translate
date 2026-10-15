# Phát triển — PDF Translate

Tài liệu cho người sửa mã. Hướng dẫn dựng & chạy cho người vận hành: `../README.md`.

## API và tính năng

Dịch tài liệu PDF, giữ nguyên bố cục, cho nhiều người dùng: đăng ký bằng email, danh sách
"Tệp của tôi" có lọc theo tên, sắp xếp theo cột (tên / ngày tạo / trạng thái), phân trang và chọn nhiều tệp để xoá hàng loạt.
API: `GET /api/files?q&page&page_size&sort=created|name|status&dir=asc|desc`; `POST /api/files/bulk-delete` với
`{"ids":[…]}` (1–100 id) hoặc `{"all":true,"q":"…"}` → `{"deleted":n,"skipped_running":m}`. Lõi dịch là [VI-Translate](https://github.com/breslee1707/VI-Translate)
(AGPL-3.0), kéo lúc build theo SHA ghim trong `Dockerfile` — không sửa mã upstream.
Dịch lại: `POST /api/files/{id}/retranslate` `{"language","engine","model","font"}` (tệp đã xong: dịch lại từ đầu, bản cũ
tải được tới khi bản mới xong; tệp lỗi: tại chỗ) và `POST /api/files/bulk-retranslate` (`ids` hoặc `all`+`q` như
bulk-delete, kèm `settings: null | {…}`) → `{"queued","skipped_pending","skipped_limit","limit"}`.

## Chạy khi phát triển

    cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))') \
    DATA_DIR=.data WORKER_CMD="python tests/fake_worker.py" \
      .venv/bin/uvicorn app.main:create_app --factory --port 8000
    cd frontend && npm ci && npm run dev        # http://localhost:5173, /api đi qua proxy tới :8000

DB trống thì mở app là gặp trình cài đặt `/setup` (tài khoản quản trị + SMTP bỏ qua được); `/setup` ghi lại địa chỉ đang mở
(ở đây `http://localhost:5173`) làm địa chỉ trang trong thư khi không đặt `APP_BASE_URL`. Không có SMTP (Cài đặt › Hệ
thống hoặc `SMTP_HOST`) thì tài khoản mới dùng ngay, không cần xác nhận; `MAIL_DEV_LOG=1` in link xác thực / đặt lại mật
khẩu ra log mà vẫn bắt xác nhận (dev / E2E).

Engine dịch: `google_free` (mặc định, không key), `google_cloud` và `gemini` (người dùng tự lưu API key ở
`/settings/translation`, mã hoá bằng khoá dẫn từ `SECRET_KEY` — xem "Đổi SECRET_KEY" trong [DEPLOY.md](DEPLOY.md)).

Cài đặt › Tài khoản (`/settings/account`): đổi tên hiển thị, đổi email (link xác nhận tới email mới, hiệu lực
24 giờ), đổi mật khẩu (đăng xuất mọi thiết bị khác), xoá tài khoản. Font chữ của bản dịch: `Tự động` /
`Không chân (Liberation Sans)` / `Có chân (Liberation Serif)` — xem "Font bản dịch" trong [DEPLOY.md](DEPLOY.md)
(kể cả bước `scripts/font-render-check.py` bắt buộc mỗi lần nâng pin upstream).

Chế độ nâng cao (Cài đặt › Dịch thuật, mỗi người tự bật, mặc định tắt): tab **Hồ sơ dịch** (`/settings/profiles`, 5 mẫu trong
`backend/app/profiles/presets.py` + tối đa 20 hồ sơ riêng); khi tải lên / dịch lại bằng Gemini chọn hồ sơ, tuỳ chỉnh riêng cho tài
liệu và điền ngữ cảnh — `backend/app/profiles/prompt.py` dựng chỉ dẫn tiếng Anh nối sau `SYSTEM_PROMPT`, runner đưa qua env
`TRANSLATE_INSTRUCTIONS` cho `handoff_worker.py`, SHA-256 vào `segments.meta.json`. Mỗi bản dịch mang ảnh chụp cấu hình
(`files.config`, JSON); dịch lại thành công thì bản cũ thành một phiên bản (`file_versions`, `versions/<id>/` trong thư mục tệp),
xem/tải ở trang chi tiết; admin đặt số bản giữ lại ở Cài đặt › Hệ thống. Google miễn phí / Cloud Translation không nhận hồ sơ.

Đợt 1b của Chế độ nâng cao: trang **Phiên bản** (`/files/:id/versions`) với thanh mốc, hai bản cạnh nhau (cấu hình + PDF) và **Khôi phục**
(`POST /api/files/{id}/versions/{vid}/restore` — một job của runner CHÉP bản cũ thành bản mới nhất, không gọi API; bảng đoạn đi theo từng
bản trong `versions/<id>/`); lần đầu bật chế độ, 5 mẫu được **gieo thành hồ sơ của chính người dùng** (`translation_profiles.preset_slug`,
nhãn "Từ mẫu"; `POST /api/profiles/restore-presets` đưa về gốc); sửa/tạo hồ sơ ngay tại ô chọn ở Cài đặt và trong hộp tải lên / dịch
lại; động cơ mặc định là thuần thì server tự tắt Chế độ nâng cao (cả khi xoá key Gemini hay Google gỡ model cuối).

## Kiểm thử

    cd backend && .venv/bin/pytest -q --cov=app   # 2026-10-15: 850 passed, 3 skipped (903 s), coverage TOTAL 96% (đợt 1b)
    cd frontend && npx vitest run --testTimeout=20000 && npx tsc --noEmit -p .   # 2026-10-15: 426 passed (40 tệp; chạy với --testTimeout=60000 vì máy dùng chung tải nặng) — 20000 là mức tối thiểu, xem ghi chú dưới
    cd e2e && npx playwright test               # cần stack docker đang chạy, xem dưới; lần chạy cuối 2026-10-08: 1 passed (1,3 phút, có kiểm Content-Type font/woff2); đợt Chế độ nâng cao đợt 1; đợt 1b (2026-10-15): CHƯA VERIFY — xem TEST_LOG.md, mục E2E, dòng 2026-10-15

Ghi chú: `--testTimeout=20000` là mức tối thiểu — trên máy dùng chung đang tải nặng hãy đặt cao hơn (vd `--testTimeout=60000`, như lần chạy 2026-10-15 cho 426 test). Với ngưỡng mặc định 5000 ms, `FileDetailPage.test.tsx` › "retranslates a done file from a dialog prefilled…" quá hạn (`Test timed out in 5000ms`, cả khi chạy riêng một tệp) trên máy đang tải nặng (load average 5–9, có tiến trình dựng image chạy song song, 2026-10-08). Với 20000 ms cả 377 test qua (lần chạy 2026-10-15). Chưa rõ test chậm cố hữu hay do tải.

## Chạy bằng Docker

    mkdir -p .build
    [ -f .build/local.env ] || echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" > .build/local.env
    export $(cat .build/local.env)
    docker compose -p pdf-translate up -d --build      # http://localhost:18081 (chỉ mở trên 127.0.0.1)
    scripts/smoke.sh e2e/fixtures/sample-2p.pdf # dịch thật một tệp 2 trang — DB trống: mở /setup tạo quản trị viên trước

`.build/local.env` giữ `SECRET_KEY` để dùng lại giữa các lần `up`/`restart` — không commit thư mục này.
`docker-compose.yml` chuyển tiếp từ shell `SETUP_TOKEN`, `SMTP_HOST` `SMTP_PORT` `SMTP_SECURITY` `SMTP_USER` `SMTP_PASSWORD`
`SMTP_FROM`, `MAIL_DEV_LOG`, `SOURCE_URL` (export trước `up`; không đặt = mặc định ở bảng dưới). Nền tảng PaaS đọc env của app
trực tiếp, không qua tệp này.
Lưu ý: từ IP ra Internet dùng chung của máy chủ thử, endpoint dịch miễn phí của Google trả captcha
nên `scripts/smoke.sh` sẽ kết thúc ở `error` thay vì `done` (xem "Việc còn treo" trong [DEPLOY.md](DEPLOY.md));
điều đó không có nghĩa là stack chạy sai — `/health` vẫn phải trả `{"status":"ok",...}`.

## E2E

E2E chạy trên container thật với DB **trống** (bắt đầu ở `/setup`) và worker dịch giả (fake worker) thay cho nhân dịch
thật: bài test chứng minh các luồng WEB (cài đặt lần đầu, Cài đặt › Hệ thống, đăng ký, upload, tiến độ, tải xuống, dựng
lại, dịch lại đơn + hàng loạt, tìm kiếm, phân trang, xoá hàng loạt, xoá, đóng/mở đăng ký, sống qua restart, bố cục
360px), còn nhân dịch thật được phủ riêng bởi `scripts/smoke.sh` ở trên.

    docker build -t vi-translate-saas:e2e -f e2e/Dockerfile.e2e backend/tests
    export $(cat .build/local.env)
    docker compose -p pdf-translate-e2e -f e2e/compose.fresh.yml down -v     # stack dùng một lần, CHỈ project pdf-translate-e2e
    docker compose -p pdf-translate-e2e -f e2e/compose.fresh.yml up -d --no-build   # http://localhost:18082
    cd e2e && npm ci && npx playwright install chromium && npx playwright test

(Lần đầu trên máy chưa có thư viện hệ thống cho Chromium, có thể cần thêm
`npx playwright install-deps chromium` trước khi chạy test.) Build image `vi-translate-saas:e2e` cần image
`vi-translate-saas:local` đã build sẵn (mục "Chạy bằng Docker" ở trên) — nó chỉ thêm 1 layer copy
`fake_worker.py` lên trên.

Tệp mẫu `e2e/fixtures/sample-2p.pdf` là PDF tổng hợp (2 trang tiếng Anh) sinh bởi `e2e/fixtures/make_sample_pdf.py` (PyMuPDF, không
phông ngoài, kết quả lặp lại được); cách sinh lại nằm ở đầu tệp đó.

Xong thì dọn: `docker compose -p pdf-translate-e2e -f e2e/compose.fresh.yml down -v` (chỉ project `pdf-translate-e2e`; stack `pdf-translate` chạy thử không bị đụng).

## Biến môi trường

Bảng đầy đủ (khoá, bắt buộc, bí mật, mặc định) nằm ở một nơi: [VIBEHOST.md](VIBEHOST.md) §4. Biến chỉ dành cho dev / vận hành nội bộ:

| Biến | Mặc định / ý nghĩa |
|---|---|
| `DATA_DIR` | `/data` |
| `MAIL_DEV_LOG` | `1`: thư in ra log nhưng tính là đã cấu hình (dev / E2E, không dùng khi deploy thật) |
| `WORKER_CMD` | `<python của app> <backend>/app/engine/font_worker.py` — worker cho `google_free`; bọc `app/engine/worker.py` để áp hồ sơ font (`TRANSLATE_FONT`). E2E ghi đè bằng worker giả |
| `HANDOFF_WORKER_CMD` | `<python của app> <backend>/app/engine/handoff_worker.py` — worker cho engine cần API key (Gemini / Google Cloud); key tới worker qua env `TRANSLATE_PROVIDER/TRANSLATE_API_KEY/TRANSLATE_MODEL` |
| `FORWARDED_ALLOW_IPS` | `*` (đặt trong Dockerfile) — IP proxy được tin `X-Forwarded-For`; thu hẹp về IP/dải mạng của proxy nếu bước kiểm trong [DEPLOY.md](DEPLOY.md) thất bại |

Mỗi thư mục dữ liệu chỉ một tiến trình chạy hàng đợi dịch (khoá `flock` trên `DATA_DIR/runner.lock`);
tiến trình thứ hai cùng `DATA_DIR` chỉ phục vụ web và tự tiếp quản khi tiến trình kia dừng.

Triển khai: [DEPLOY.md](DEPLOY.md) (mục "Ổ lưu trữ bền cho `/data`": **bắt buộc** gắn ổ bền cho `/data`). Kiểm chứng đã chạy: [TEST_LOG.md](TEST_LOG.md).
