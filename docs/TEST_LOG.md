# Nhật ký kiểm chứng — PDF Translate

Ghi lại những gì đã được chạy thật, ngày nào, bằng lệnh nào, kết quả ra sao. Chỗ nào chưa chạy thì ghi **CHƯA CHẠY**. Môi trường
thử: Docker 29.1.3 trên một máy chủ nội bộ (Docker-in-Docker, 12 lõi, đĩa hạn chế); không phải Vibe Host hay PaaS nào. Số đo
RAM/CPU ở [MEASUREMENTS.md](MEASUREMENTS.md); việc còn treo ở [DEPLOY.md](DEPLOY.md) và [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

Mã commit dưới đây là của lịch sử phát triển nội bộ; bản đẩy lên GitHub là một commit gộp nên các mã này có thể không còn trong
repo công khai.

## Build đầy đủ từ `Dockerfile`

| Ngày | Lệnh | Kết quả |
|---|---|---|
| 2026-10-01 | `docker build -t vi-translate-saas:local .` (commit `65d2ac4`) | rc=0, ~27 phút; image 2,69 GB disk usage / 764 MB content size; đĩa trống 13 GB trước build, 8,6 GB sau build + fixture |
| 2026-10-06 | `docker build -t vi-translate-saas:local .` (commit `93e5212`, sau khi Docker của máy thử bị xoá sạch) | rc=0, **33 phút**; image 2,69 GB |

Hai số (27 và 33 phút) chênh nhau, chưa đo lại. **Từ khi `Dockerfile` đổi sang user thường (uid 10001, 2026-10-07) chưa có build
đầy đủ nào** vì máy thử thiếu đĩa; các lần sau đó dựng một lớp mỏng thay mã backend / giao diện / `docker-entrypoint.sh` lên trên
image đầy đủ 2026-10-06 (lặp lại phần user thường của `Dockerfile`), rồi chạy các bước kiểm dưới đây. Cần dựng đầy đủ rồi chạy
lại các bước kiểm uid 10001 trước khi coi `Dockerfile` hiện tại là đã kiểm.

## Kiểm trong image (user thường uid 10001)

Image dựng mỏng từ commit `b8a5a52` (mã backend của `4078a35` + `Dockerfile` / `docker-entrypoint.sh` đã siết), 2026-10-08, sau
review vòng 1.

| Việc kiểm | Lệnh / cách làm | Kết quả |
|---|---|---|
| Danh tính tiến trình | `docker run --rm --network none <image> sh -c 'id -u; ls -ld /data'` | uid 10001, `/data` thuộc `app app` |
| Không còn tệp setuid/setgid | `find / -xdev -perm /6000 -type f` trong image | rỗng |
| Biến môi trường | `echo $HOME` | `/home/app` |
| Chạy với `no-new-privileges` | `docker inspect` stack thử | `SecurityOpt` có `no-new-privileges:true` |
| Kiểm hiển thị font | `scripts/font-render-check.py` (uid 10001, `--network none`) | `FONT RENDER CHECK: PASSED` |
| Thư mục host thuộc root, chạy mặc định | bind mount thư mục thuộc root vào `/data` | thoát mã 1 kèm `LỖI: tiến trình app (uid=10001 gid=10001) không ghi được vào /data …` |
| Cùng thư mục, bật một lần bằng `--user 0` | `docker run --user 0 …` | `/health` 200, PID 1 `Uid 10001`, `CapBnd 0`, `NoNewPrivs 1`, thư mục thành `10001:10001` |
| `--user` khác | `--user 12345` | thoát mã 1: "chỉ hỗ trợ uid 10001 … hoặc user 0" |
| `DATA_DIR=/` với `--user 0` | `--user 0 -e DATA_DIR=/` | bị từ chối; `docker diff` rỗng (không chown gì) |
| Migration tự nâng | DB demo `0006` → `0007` lúc khởi động | số dòng mọi bảng trước / sau bằng nhau (users 1, files 1) |
| Python trong image | `docker run --rm --entrypoint python <image> --version` | 3.12.15 |
| Khởi động → `/health` 200 | `docker run` rồi vòng `curl -sf /health` | 2,7 s (app rảnh RSS 97 MB sau 30 s) |

## Sao lưu / khôi phục / lùi bản

| Ngày | Việc | Kết quả |
|---|---|---|
| 2026-10-08 | Lệnh sao lưu `tar` và khôi phục của README chạy trên volume tạm | tệp và quyền sở hữu (app) được giữ; tệp ghi sau lúc sao lưu biến mất sau khi khôi phục |
| 2026-10-08 | Image cũ chạy trên SQLite đóng dấu revision `0099_future` (mã không biết) | `upgrade_db` ném `alembic.util.exc.CommandError: Can't locate revision identified by '0099_future'`, app không khởi động, thoát mã 1 |
| 2026-10-03 | Nâng DB `0003` → `0004` với bản sao DB và tag image cũ giữ sẵn | DB lên `0004` tự động lúc khởi động; tài khoản demo và 5 tệp còn nguyên |
| 2026-10-06 | Nâng lên `0005` | không có bản ghi: Docker của máy thử bị xoá trước đó, demo bắt đầu thẳng ở `0005` trên DB trống, không có gì để lui |
| — | Lệnh hạ cấp DB bằng image mới (`DEPLOY.md`, mục lùi bản (b)) | **CHƯA có bản ghi đã chạy lại** trong tài liệu này; chạy thử trên bản sao DB trước khi dựa vào |

## Bộ kiểm thử tự động

| Ngày | Lệnh | Kết quả |
|---|---|---|
| 2026-10-08 | `cd backend && .venv/bin/pytest -q --cov=app` | 693 passed, 3 skipped (327 s) |
| 2026-10-08 | `cd frontend && npx vitest run --testTimeout=20000 && npx tsc -p .` | 314 passed; `tsc` sạch. Cờ `--testTimeout=20000` bắt buộc: ngưỡng mặc định 5000 ms làm `FileDetailPage.test.tsx` quá hạn trên máy đang tải nặng |
| 2026-10-03 → 2026-10-08 | test cần PyMuPDF chạy trong image (`pytest` trong container, không có trong `backend/.venv`) | 62 passed (lần ghi 2026-10-06) |

## E2E (Playwright, container thật, DB trống, worker dịch giả)

Stack dùng một lần từ `e2e/compose.fresh.yml` (xem [DEVELOPMENT.md](DEVELOPMENT.md), mục "E2E"): image `:e2e`
(`e2e/Dockerfile.e2e`), `MAIL_DEV_LOG=1`, cổng `127.0.0.1:18082`. Bài `e2e/tests/golden-path.spec.ts` đi qua `/setup`, Cài đặt ›
Hệ thống, đăng ký, tải lên, tiến độ, tải xuống, dựng lại, dịch lại đơn + hàng loạt, tìm kiếm, phân trang, xoá hàng loạt, đóng /
mở đăng ký, sống qua restart, bố cục 360 px, và kiểm trang không có yêu cầu tới bên thứ ba (phông tự host, Content-Type
`font/woff2`).

| Ngày | Kết quả |
|---|---|
| 2026-10-03 | `1 passed` trên image dựng mỏng từ `08ac773` |
| 2026-10-06 | `1 passed` (cả sau đợt sửa của review tổng); smoke `scripts/smoke.sh` (luồng API, worker giả) `OK` hai lượt |
| 2026-10-07 | `1 passed` (≈ 1,2–1,3 phút) trên image user thường |
| 2026-10-08 | `1 passed` (≈ 1,3 phút) sau review vòng 1, có kiểm Content-Type font/woff2 |
| 2026-10-08 (sau khi dọn dữ liệu nội bộ) | `1 passed` (1,3 phút) với tệp mẫu `e2e/fixtures/sample-2p.pdf` mới (PDF tổng hợp sinh bởi `e2e/fixtures/make_sample_pdf.py`); `backend` 693 passed, 3 skipped (`pytest -q -W error::ResourceWarning`, 334 s); `frontend` 314 passed + `tsc` sạch |

## Dịch thật (engine thật)

| Engine | Trạng thái |
|---|---|
| `google_free` | **CHƯA TỪNG CHẠY ĐƯỢC** đầu-cuối: Google trả 429 + trang captcha cho IP egress dùng chung của máy thử, xác nhận bằng `curl` từ cả máy chủ lẫn container, thử lại 3 lần thật trong ~20 phút (`MEASUREMENTS.md`) |
| `gemini`, `google_cloud` | **CHƯA VERIFY** với khoá thật: toàn bộ test dùng transport giả |

## Chưa chạy trên nền tảng thật

Chưa có lượt triển khai nào trên Vibe Host hay PaaS bên ngoài: reverse proxy thật, `X-Forwarded-Proto` / `X-Forwarded-For`, giới
hạn thân yêu cầu, gắn ổ bền vào `/data`, `--cpus` (CFS) đều **CHƯA CHẠY**. Các bước kiểm cần chạy ở đó: "Kiểm sau khi triển khai"
trong [DEPLOY.md](DEPLOY.md).
