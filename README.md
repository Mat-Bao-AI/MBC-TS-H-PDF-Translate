# PDF Translate

Dịch tài liệu PDF giữ nguyên bố cục, cho nhiều người dùng: đăng ký bằng email, danh sách "Tệp của tôi", dịch lại, tải xuống.
Dữ liệu (SQLite nhúng `app.db` + tệp người dùng) nằm ở `/data`; không cần cơ sở dữ liệu ngoài. Lõi dịch là
[VI-Translate](https://github.com/breslee1707/VI-Translate) của breslee1707 (AGPL-3.0; tác giả gốc), kéo lúc build theo commit ghim trong `Dockerfile` từ nhánh `main` của chính repo này (bản fork của Mắt Bão, `https://github.com/Mat-Bao-AI/MBC-TS-H-PDF-Translate`); mã của dự án nằm ở nhánh `pdf-translate-saas`, không sửa mã upstream.

Phiếu nộp mẫu Vibe Host (cổng, RAM/CPU, bảng biến môi trường): [docs/VIBEHOST.md](docs/VIBEHOST.md).

## Yêu cầu trước

| Mục | Giá trị | Nguồn |
|---|---|---|
| Docker | 29.1.3 (bản đã chạy thật, máy chủ thử nội bộ) | `docker version` |
| Docker Compose | 2.40.3 (cùng máy chủ thử; chỉ cần cho cách chạy bằng compose) | `docker compose version` |
| Image nền | `python:3.12-slim` (chạy), `node:22-slim` (chỉ lúc build giao diện). Bản đã chạy: Python 3.12.15 trong image (`docker run --rm --entrypoint python vi-translate-saas:local --version`, 2026-10-08); Node v22.23.2 build giao diện (`node -v` trên máy dựng — bản dựng mỏng biên dịch giao diện trên máy chủ, `docs/TEST_LOG.md`) | `Dockerfile` |
| Cỡ image | 2,69 GB (build đầy đủ; `docs/TEST_LOG.md` ghi 2,69 GB ở build 2026-10-06, `docs/MEASUREMENTS.md` ghi 2.69 GB ở build đầu 2026-10-01); bản dựng mỏng hiện tại 2,88 GB (`docker images`, 2026-10-08) | `docs/MEASUREMENTS.md`, `docs/TEST_LOG.md` |
| RAM | 2 GB. Ước tính đỉnh khi dịch 1 tệp 100 trang: 1020 MB = tổng hai số đo riêng (app rảnh 97 MB + worker chạy độc lập 923 MB, `docs/MEASUREMENTS.md` 2026-10-07), chưa đo cả hai chạy cùng lúc. Số tham khảo của bản bọc trước trên 288 trang: worker 1.353 MiB (`docs/MEASUREMENTS.md`, mục "Số đo tham khảo của bản bọc trước"). Tài liệu > 100 trang của bản này: CHƯA ĐO | `docs/VIBEHOST.md` §3, `docs/MEASUREMENTS.md` |
| CPU | 2 nhân. Phần nặng ≈ 4,5 phút / 15 trang, ≈ 27 phút / 100 trang ở 2 nhân (chưa tính thời gian gọi mạng dịch) | `docs/MEASUREMENTS.md` (2026-10-07) |
| Đĩa cho `/data` | CHƯA ĐO — chưa có số đo dung lượng theo người dùng (tệp tải lên tối đa 50 MB mỗi tệp, `MAX_UPLOAD_MB`) | `docs/DEPLOY.md` "Việc còn treo" |
| Đĩa để build | ≥ 12 GB trống (ngưỡng ghi ở `docs/DEPLOY.md`, "Dựng image"); đo ở build đầu 2026-10-01 (commit `65d2ac4`): trước build 13 GB trống, sau build + fixture 8,6 GB | `docs/DEPLOY.md`, `docs/MEASUREMENTS.md` |
| Mạng ra ngoài (lúc chạy) | `translate.google.com` cho engine miễn phí `google_free`; `generativelanguage.googleapis.com` (Gemini) hoặc `translation.googleapis.com` (Cloud Translation) khi người dùng lưu API key riêng. SMTP: tuỳ chọn | `docs/MEASUREMENTS.md`, `docs/DEPLOY.md` |
| Mạng ra ngoài (lúc build) | `github.com` (mã upstream), PyPI, npm, nguồn tải model bố cục (`huggingface.co`) | `Dockerfile`, `babeldoc/assets/embedding_assets_metadata.py` trong image |

## Lệnh dựng & chạy

Dựng (build lạnh: 33 phút theo `docs/TEST_LOG.md` mục "Build đầy đủ"; ~27 phút theo `docs/MEASUREMENTS.md` ở lần dựng đầu — hai số chênh nhau, chưa đo lại):

    docker build -t pdf-translate .

Chạy bằng `docker run`, volume có tên gắn vào `/data`, cổng 8000:

    export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))'); echo "$SECRET_KEY"   # lưu lại, dùng lại ở mọi lần nâng cấp
    export SETUP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))'); echo "$SETUP_TOKEN"   # mã cài đặt, gõ lại ở bước "Tài khoản đầu tiên"
    docker run -d --name pdf-translate --restart on-failure \
      -p 127.0.0.1:8000:8000 -v pdf-translate-data:/data \
      --security-opt no-new-privileges:true \
      -e SECRET_KEY -e SETUP_TOKEN \
      pdf-translate

Chạy bằng docker compose (`docker-compose.yml`; mở `http://localhost:18081`, chỉ trên 127.0.0.1):

    mkdir -p .build
    [ -f .build/local.env ] || echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" > .build/local.env
    export SETUP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))'); echo "$SETUP_TOKEN"   # mã cài đặt, gõ lại ở "Tài khoản đầu tiên"
    export $(cat .build/local.env)
    docker compose -p pdf-translate up -d --build

- `.build/local.env` giữ `SECRET_KEY` giữa các lần `up` — không commit thư mục `.build/`.
- Bảng biến môi trường đầy đủ (khoá, bắt buộc, bí mật, mặc định): [docs/VIBEHOST.md](docs/VIBEHOST.md) §4. `SECRET_KEY` là biến bắt buộc của app (≥ 32 ký tự; thiếu hoặc ngắn hơn thì app không khởi động, `backend/app/config.py`). `SETUP_TOKEN` app không bắt buộc: để trống thì người đầu tiên mở `/setup` trở thành quản trị viên, nên **nên đặt**; trong mẫu Vibe Host nó là biến bắt buộc (`docs/VIBEHOST.md` §4).
- Phía trước cần reverse proxy HTTPS (cookie phiên đặt `Secure`): `http://` chỉ chạy được trên `localhost` / `127.0.0.1`.
- Image chạy bằng uid/gid 10001, không phải root (xem "Lỗi thường gặp").

## Dấu hiệu đã chạy

- `GET /health` trả HTTP 200, thân `{"status":"ok","queue":0}` (`queue` = số tệp đang chờ dịch; `backend/app/main.py`). Không cần đăng nhập.

      curl -sf http://127.0.0.1:8000/health

- Cài mới (CSDL trống): `GET /api/setup/status` trả `"needs_setup": true`; mở `/` thì trình duyệt chuyển sang `/setup` (`frontend/src/App.tsx`, `App.test.tsx`). `GET /` và `/setup` đều trả 200 trước và sau khi cài.
- Phân biệt "container sống nhưng app chết":
  - `docker ps` báo `Up` chưa đủ. `/health` phải trả 200 với đúng thân trên; container có `HEALTHCHECK` (`curl -sf /health` mỗi 30 s, `Dockerfile`) nên `docker ps` ghi `(healthy)` khi đạt.
  - App không khởi động được (thiếu / ngắn `SECRET_KEY`, `/data` không ghi được, migration lỗi) thì tiến trình thoát và `docker logs pdf-translate` ghi lý do ngay dòng cuối.
  - `/health` 200 nhưng dịch hỏng: `docker logs` có lỗi worker; nguyên nhân thường gặp ở "Lỗi thường gặp" (b).

## Tài khoản đầu tiên

1. Mở `/` → được chuyển sang `/setup`.
2. Nhập `SETUP_TOKEN` (giá trị bạn đặt lúc chạy), email và mật khẩu quản trị. Bước SMTP bỏ qua được.
3. Người nhập đúng mã ở bước này là quản trị viên. Trước bước này đăng ký / đăng nhập trả 409 `setup_required`.
4. Sau khi cài, `POST /api/setup` trả 409 `setup_done`; mở lại trang `/setup` thì trình duyệt tự chuyển về `/` (`GET /setup` vẫn trả 200, vì là vỏ SPA). Tín hiệu đọc bằng máy: `GET /api/setup/status` → `{"needs_setup": false, …}`. Đóng đăng ký công khai (nếu không muốn người lạ tự đăng ký): Cài đặt › Hệ thống.

Cài trên instance không đặt `APP_BASE_URL`: `/setup` ghi lại địa chỉ trình duyệt đang mở làm địa chỉ trang trong thư. Không có địa chỉ nào (không env, không ghi được) thì thư có liên kết bị tắt, tài khoản mới dùng ngay không cần xác nhận email.

## Nâng cấp & lùi bản

**Nâng cấp** = dựng lại image từ mã mới (hoặc đổi tag / git ref), dừng container cũ, chạy lại với **cùng volume `/data` và cùng `SECRET_KEY`**:

    # 1. Sao lưu /data TRƯỚC (container dừng hẳn để SQLite không ghi dở)
    docker stop pdf-translate
    docker run --rm --user 0 -v pdf-translate-data:/data:ro -v "$PWD":/backup --entrypoint tar pdf-translate \
      czf /backup/pdf-translate-data-$(date +%Y%m%d-%H%M).tgz -C /data .
    # 2. Dựng bản mới và chạy lại với cùng volume + cùng SECRET_KEY
    docker tag pdf-translate pdf-translate:prev   # giữ image cũ để lùi bản
    docker build -t pdf-translate .
    docker rm pdf-translate
    # rồi chạy lại đúng lệnh `docker run -d --name pdf-translate …` ở "Lệnh dựng & chạy"; SECRET_KEY phải là giá trị cũ

- Migration chạy tự động lúc khởi động (`upgrade_db` → alembic `head`, `backend/app/main.py` lifespan, `backend/app/db.py`). Bản mới nhất hiện có là `0009_versions_restore_profiles_seed`.
- Từ `0008` mỗi tệp có thể giữ các bản dịch cũ (`file_versions`, tệp ở `/data/users/<user>/<file>/versions/`). **Lùi về trước `0008`**
  (khôi phục bản sao lưu DB cũ) làm mất danh sách bản cũ trong DB; thư mục `versions/` trên đĩa trở thành rác vô hại — xoá tệp sẽ dọn
  theo. Số bản giữ lại đặt ở Cài đặt › Hệ thống (1–10, mặc định 3, tính cả bản hiện tại).
- Từ `0009` (đợt 1b): bản cũ mang theo bảng đoạn đã dịch (`versions/<id>/segments.*`), có giờ dịch (`translated_at`) và có thể được
  **khôi phục** thành bản mới nhất (nút "Phiên bản cũ (N)" ở trang chi tiết → trang Phiên bản); 5 hồ sơ mẫu được chép thành hồ sơ riêng
  lần đầu bật Chế độ nâng cao (`translation_profiles.preset_slug`, `users.profiles_seeded`), kèm chỉ mục duy nhất
  `(user_id, preset_slug)`. **Lùi về `0008`** (downgrade bỏ bảy cột và chỉ mục này) mất nhãn "khôi phục từ", giờ dịch của bản, cờ
  gieo và liên kết hồ sơ–mẫu (5 dòng đã gieo thành hồ sơ riêng thường); không mất tệp.
- **Dữ liệu khách có mất không: không**, miễn volume `/data` được giữ. Mất `/data` = mất tài khoản + tệp (xem (a) ở "Lỗi thường gặp").
- **Đổi `SECRET_KEY` thì API key (Gemini / Cloud Translation) và mật khẩu SMTP đã lưu trong DB không giải mã được.** Phải nhập lại API key ở Cài đặt › Dịch thuật và mật khẩu SMTP ở Cài đặt › Hệ thống. Tài khoản, mật khẩu đăng nhập và tệp không bị ảnh hưởng (`docs/DEPLOY.md`, "Đổi SECRET_KEY").

**Lùi bản**: migration chỉ đi tiến trong thực tế. Đã kiểm 2026-10-08 (image `vi-translate-saas:pre-nonroot`, một tệp SQLite tạm đóng dấu revision `0099_future` mà mã không biết): `upgrade_db` ném `alembic.util.exc.CommandError: Can't locate revision identified by '0099_future'`, lifespan lỗi, app không khởi động (lệnh thử thoát mã 1). Nghĩa là image cũ **không chạy được** trên CSDL đã nâng lên revision mới hơn nó biết. Lùi bản vì vậy cần khôi phục bản sao lưu:

    docker stop pdf-translate && docker rm pdf-translate
    export BACKUP=$(ls -t pdf-translate-data-*.tgz | head -1); echo "$BACKUP"   # tệp sao lưu mới nhất ở thư mục hiện tại; đổi nếu muốn bản khác
    docker run --rm --user 0 -e BACKUP -v pdf-translate-data:/data -v "$PWD":/backup:ro --entrypoint sh pdf-translate \
      -c 'find /data -mindepth 1 -delete && tar xzf "/backup/$BACKUP" -C /data'
    # rồi chạy image CŨ (pdf-translate:prev) với đúng volume và SECRET_KEY cũ

Hai lệnh sao lưu / khôi phục đã chạy thử 2026-10-08 trên volume tạm với image `vi-translate-saas:local`: tệp và quyền sở hữu (app) được giữ, tệp ghi sau lúc sao lưu biến mất sau khi khôi phục.

Thay đổi người dùng thực hiện sau lúc sao lưu (tài khoản mới, tệp mới) mất khi khôi phục.

## Lỗi thường gặp

**(a) Đăng nhập báo sai / danh sách tệp trống sau khi deploy lại hoặc bật lại**
- Nguyên nhân: `/data` không phải ổ bền (volume vô danh do `VOLUME ["/data"]`, hoặc volume bị xoá). Đã gặp 2026-10-06 trên máy chủ thử: khởi động lại làm Docker bị xoá sạch (image + volume), mất tài khoản demo cũ (`docs/KNOWN_ISSUES.md`).
- Xử lý: gắn volume có tên (hoặc thư mục host) vào `/data` như ở "Lệnh dựng & chạy". Kiểm: tạo tài khoản, tải một tệp, khởi động lại container, đăng nhập lại — tài khoản và tệp còn nguyên.

**(b) Dịch báo lỗi (`Failed to translate`), job ở trạng thái `error`, engine "miễn phí"**
- Nguyên nhân: endpoint dịch miễn phí của Google (`translate.google.com/m`) trả 429 + trang captcha cho IP egress dùng chung. Đã gặp từ IP ra Internet dùng chung của máy chủ thử, thử 3 lần trong ~20 phút đều bị chặn (`docs/MEASUREMENTS.md`). `/health` vẫn 200.
- Xử lý: người dùng lưu API key Gemini hoặc Google Cloud Translation của riêng mình ở Cài đặt › Dịch thuật rồi chọn engine đó. Bản dịch thật qua các key này: CHƯA VERIFY với key thật (`docs/DEPLOY.md` "Việc còn treo").

**(c) Container thoát ngay sau khi bật, `docker logs` có "LỖI: tiến trình app (uid=10001 …) không ghi được vào /data"**
- Nguyên nhân: image chạy bằng uid 10001; thư mục host gắn vào `/data` (hoặc volume do image cũ chạy root ghi) thuộc root. Đã gặp khi kiểm với thư mục thuộc root: exit 1 kèm thông báo này (`docs/TEST_LOG.md`, mục "Kiểm trong image": thư mục host thuộc root → thoát 1 kèm thông báo, cùng thư mục với `--user 0` → `/health` 200, PID 1 `Uid 10001`; cách xử lý: `docs/DEPLOY.md`, "Chạy bằng user thường").
- Xử lý, chọn một: `chown -R 10001:10001 <thư mục host>`; hoặc dừng container cũ rồi bật MỘT lần với `--user 0` (entrypoint trao quyền `/data` cho uid 10001 rồi tự hạ về 10001, không capability, `no-new-privs`), sau đó bỏ `--user 0`. Chỉ hỗ trợ uid 10001 hoặc user 0; `--user` khác thoát mã 1 kèm thông báo.

## Giấy phép

- GNU AGPL-3.0: [LICENSE](LICENSE). Thông báo bản quyền và thành phần bên thứ ba: [NOTICE](NOTICE).
- Người vận hành cho người ngoài truy cập qua mạng phải cung cấp mã nguồn của bản đang chạy (AGPL §13): đặt `SOURCE_URL` (`https://…`) trỏ tới kho mã công khai. Liên kết "Mã nguồn" ở chân trang chỉ hiện khi `SOURCE_URL` có giá trị (`frontend/src/components/AppShell.tsx`).
- Quản lý duyệt AGPL-3.0 cho bản công khai: chưa có (`docs/VIBEHOST.md`, "Việc còn lại trước khi nộp").

## Phát triển

Chạy dev, kiểm thử, E2E, API: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Triển khai trên máy chủ Docker / PaaS: [docs/DEPLOY.md](docs/DEPLOY.md). Nhật ký kiểm chứng: [docs/TEST_LOG.md](docs/TEST_LOG.md). Số đo: [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md). Việc còn treo: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).
