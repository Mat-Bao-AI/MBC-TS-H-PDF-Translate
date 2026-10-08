# Phiếu nộp mẫu Vibe Host — PDF Translate

Chuẩn: tài liệu yêu cầu `yc-deploy` của danh mục mẫu Vibe Host (mục 0–9 + "Bằng chứng đã chạy thật"). Mỗi mục dưới đây là giá trị gõ vào nền tảng.
Số đo lấy từ `docs/MEASUREMENTS.md` và `docs/TEST_LOG.md`; chỗ chưa đo ghi **CHƯA ĐO**, chưa biết ghi **CHƯA BIẾT**.
Hướng dẫn cho người vận hành nằm ở `README.md` (đủ 6 mục của mục 8).

## 0. Đường đi: Git

| Trường | Giá trị |
|---|---|
| Đường | Mã nguồn Git |
| `repoUrl` | `https://github.com/Mat-Bao-AI/MBC-TS-H-PDF-Translate` — công khai; là fork của upstream: nhánh `main` = bản sao upstream (giữ nguyên, Dockerfile kéo lõi từ đây), mã dự án ở nhánh `pdf-translate-saas` |
| `gitRef` | `pdf-translate-saas` (hoặc tag khi có bản phát hành) — KHÔNG phải `main` (main là mã upstream) |
| `subdir` | để trống (Dockerfile ở gốc repo) |

- Build lạnh toàn bộ: 33 phút (`docs/TEST_LOG.md`, mục "Build đầy đủ", build đầy đủ commit `93e5212`); `docs/MEASUREMENTS.md` ghi ~27 phút ở lần build đầu trước đó. Hai số chênh nhau, chưa đo lại.
- Cỡ image: 2,69 GB (cùng mục `docs/TEST_LOG.md`; `docs/MEASUREMENTS.md`: 2,69 GB disk usage / 764 MB content size). Bản dựng mỏng hiện tại (sau khi đổi sang uid 10001): 2,88 GB theo `docker images vi-translate-saas:local`, 2026-10-08.
- Thời gian chờ build tối đa của nền tảng: **CHƯA BIẾT**. Nếu ngắn hơn 33 phút: đường thay thế là nộp ảnh Docker đã dựng sẵn (`ảnh:tag`) — chưa có ảnh công khai nào (**chờ đẩy lên registry**).
- **Câu hỏi mở (quyết định đường nộp phụ thuộc vào đây): nền tảng build một lần cho mỗi mẫu, hay build lại ở mỗi lượt deploy của khách?**
  - Nếu mỗi lượt deploy: mỗi khách chờ trọn build lạnh (33 phút đo ở `docs/TEST_LOG.md`, ~27 phút ở `docs/MEASUREMENTS.md`) và nền tảng phải ra được `github.com`, `huggingface.co` (`scripts/fetch_assets.py` của upstream), PyPI, npm.
  - Nếu mỗi lượt deploy: đường ảnh Docker dựng sẵn trở thành đường chính. Khi đó các giấy phép model / phông ghi **CHƯA XÁC MINH** trong `NOTICE` (mục "Tài sản được nướng vào image": model `doclayout.onnx`, phông GoNotoKurrent) thành điều kiện chặn, vì ảnh phân phối lại chúng.
  - Nếu build một lần cho mỗi mẫu: giữ đường Git như đề xuất.
- Build kéo mã upstream từ GitHub lúc build (`Dockerfile`: `UPSTREAM_REPO` = nhánh `main` của chính repo này (fork của Mắt Bão), `UPSTREAM_REF` = commit ghim; tác giả gốc: `breslee1707/VI-Translate`) — cần mạng ra `github.com`, `huggingface.co` (model bố cục, qua trình nạp tài sản của BabelDOC) và PyPI / npm.

## 1. Nội dung repo

| Yêu cầu | Trạng thái | Nguồn |
|---|---|---|
| `Dockerfile` chạy được | Có. Build đầy đủ lần cuối 2026-10-06; sau khi đổi sang user thường mới kiểm bằng bản dựng mỏng tương đương — **chưa dựng đầy đủ** | `docs/DEPLOY.md` "Việc còn treo", `docs/TEST_LOG.md` |
| Hướng dẫn deploy theo mục 8 | Có — `README.md` (6 mục) | `README.md` |
| Tệp cấu hình mục 7 | Không cần | §7 dưới đây |
| Giấy phép | `LICENSE` (AGPL-3.0), `NOTICE` | gốc repo |
| Repo công khai | Có — fork công khai của upstream (GitHub không cho fork của repo công khai ở chế độ riêng tư) | §"Việc còn lại" |

Lưu ý: spec nền tảng ghi repo mẫu nằm dưới một tổ chức GitHub mặc định khác (`github.com/<tổ-chức-mặc-định>/<tên-mẫu>`), nhưng repo này nằm dưới tổ chức `Mat-Bao-AI` (tài khoản GitHub công ty của Mắt Bão, do chủ sở hữu chọn). Người duyệt cần xác nhận cách đặt này chấp nhận được.

## 2. Nhận dạng

| Trường | Giá trị |
|---|---|
| `name` | `PDF Translate` — trùng tên với mẫu đã có trên hệ: **CHƯA KIỂM** |
| `category` | `Công cụ · AI` |
| `iconUrl` | để trống (chưa có logo → icon mặc định) |
| `description` | (357 ký tự, giới hạn 500; đếm bằng `python3 -c 'print(len(s))'`) |

```
Dịch tài liệu PDF giữ nguyên bố cục, cho nhiều người dùng: đăng ký bằng email, danh sách tệp, dịch lại, tải xuống. Dịch bằng Google miễn phí, hoặc bằng khoá Gemini / Google Cloud Translation của chính người dùng. Dữ liệu lưu trong SQLite nhúng tại /data, không cần cơ sở dữ liệu ngoài. Người đặt mã SETUP_TOKEN và mở /setup đầu tiên trở thành quản trị viên.
```

## 3. Thông số chạy

| Trường | Giá trị | Ghi chú |
|---|---|---|
| `port` | `8000` | `Dockerfile` `EXPOSE 8000`, uvicorn `--host 0.0.0.0 --port 8000` |
| `ram` | `2GB` | xem dưới |
| `cpu` | `2` | xem dưới |
| `healthPath` | `/health` | không cần đăng nhập; trả 200 `{"status":"ok","queue":0}` (`backend/app/main.py`) |

**RAM `2GB`** (quyết định; khuyến nghị gốc của phép đo là 1,5 GB — `docs/MEASUREMENTS.md`, mục 2026-10-07):
- Đỉnh khi có 1 job = app rảnh 97 MB + tiến trình worker 923 MB (tài liệu 100 trang) = 1020 MB (`docs/MEASUREMENTS.md` 2026-10-07).
- RSS của worker tăng ≈ 3,9 MB mỗi trang (590 MB ở 15 trang → 923 MB ở 100 trang: (923 − 590) / 85; cùng mục).
- Số đo tham khảo của bản bọc trước (cùng lõi upstream, kiến trúc khác): đỉnh RAM 1.353 MiB trên tài liệu 288 trang, đo 2026-09-04 — chi tiết và điều kiện ở `docs/MEASUREMENTS.md`, mục "Số đo tham khảo của bản bọc trước". Tệp tải lên tới 50 MB (`MAX_UPLOAD_MB`) cho phép tài liệu cỡ ~300 trang.
- (97 + 1.353) × 1,25 ≈ 1.81 GB → `2GB`. Tài liệu ≤ 100 trang vừa 1,5 GB (1020 × 1,25 = 1275 MB → 1536 MB). Tài liệu > 100 trang của bản SaaS này: **CHƯA ĐO** (số 288 trang là của bản bọc trước).
- Chỉ tính 1 job cùng lúc (`MAX_CONCURRENT_JOBS` mặc định 1); nhiều job đồng thời: **CHƯA ĐO**.

**CPU `2`** (`docs/MEASUREMENTS.md` 2026-10-07, ghim cứng 2 lõi bằng `--cpuset-cpus`, chỉ phần nặng: tách + dựng PDF, chưa tính thời gian gọi mạng dịch):
- 15 trang: ≈ 4,5 phút (137,2 s + 130,8 s) ở 2 lõi; 1 lõi ≈ 7,8 phút (233,7 s + 233,8 s); không giới hạn ≈ 58 s (28,4 s + 29,1 s).
- 100 trang: ≈ 27 phút ở 2 lõi (821,2 s + 785,7 s); 1 lõi **CHƯA ĐO** (ước ~47 phút, ngoại suy). Muốn nhanh hơn cho tài liệu dài: ≥ 4 lõi (15 trang: 4 lõi ≈ 2,7 phút).
- `--cpus` (quota CFS) không dùng được trong Docker-in-Docker của máy chủ thử (cgroup v2 threaded mode) nên đo bằng cpuset; cách nền tảng áp hạn mức CPU lên container: **CHƯA ĐO**.
- onnxruntime mở số luồng theo số lõi của máy chủ (12 ở máy đo), không theo số lõi được cấp → dưới hạn mức CPU thì tốn thêm CPU-giây (282 → 501 CPU-s cho 15 trang ở 2 lõi). Việc giới hạn luồng chưa làm: `docs/KNOWN_ISSUES.md`, "Đóng gói Vibe Host (2026-10-07)".

## 4. Biến môi trường (16 biến; giới hạn nền tảng 50)

Nguồn: `backend/app/config.py` (`load_settings`). Quy tắc `yc-deploy`: biến `secret` không có `default`.

| key | required | secret | generated | default | Ghi chú |
|---|---|---|---|---|---|
| `SECRET_KEY` | true | true | true | — | ≥ 32 ký tự: ngắn hơn hoặc thiếu thì app từ chối khởi động (`backend/app/config.py`). Khoá dẫn xuất mã hoá API key / mật khẩu SMTP đã lưu: đổi khoá thì các giá trị đã lưu không giải mã được (`docs/DEPLOY.md`, "Đổi `SECRET_KEY`"). `generated=true` chỉ đúng nếu giá trị nền tảng sinh **dài ≥ 32 ký tự** và **giữ nguyên qua redeploy / restart** — cả hai **CHƯA BIẾT**. Nếu một trong hai không đạt: đổi thành `generated=false`, khách dán giá trị sinh bằng lệnh `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` |
| `APP_BASE_URL` | false | false | false | — | Để trống: địa chỉ trang ghi lại từ trình duyệt lúc chạy `/setup`. Đặt khi gắn tên miền riêng (`https://…`; `http://` chỉ cho localhost). Biến thắng địa chỉ đã ghi. Không có địa chỉ nào thì thư có liên kết bị tắt |
| `SETUP_TOKEN` | true | true | **false** | — | Khách tự chọn lúc deploy và gõ lại ở `/setup`. Không đánh generated: giá trị sinh ra bị niêm, khách không đọc được → không vào được `/setup`. Đây là chỗ đóng lỗ "ai thấy địa chỉ trước thì thành admin" của mục 6 |
| `SOURCE_URL` | false | false | false | `https://github.com/Mat-Bao-AI/MBC-TS-H-PDF-Translate/tree/pdf-translate-saas` | Link "Mã nguồn" ở chân trang (AGPL §13); phải `https://`. Phải trỏ tới mã nguồn công khai của bản đang chạy |
| `SMTP_HOST` | false | false | false | — | Có thì bắt buộc `SMTP_FROM` |
| `SMTP_PORT` | false | false | false | — (587; 465 khi `SMTP_SECURITY=ssl`) | |
| `SMTP_SECURITY` | false | false | false | `starttls` | `starttls` / `ssl` / `none`; chứng chỉ máy chủ luôn được kiểm |
| `SMTP_USER` | false | false | false | — | |
| `SMTP_PASSWORD` | false | true | false | — | |
| `SMTP_FROM` | false | false | false | — | |
| `MAX_UPLOAD_MB` | false | false | false | `50` | Hạn mức thân yêu cầu phía proxy của nền tảng: **CHƯA BIẾT** |
| `MAX_CONCURRENT_JOBS` | false | false | false | `1` | Mỗi job ~1 GB RAM ở 100 trang — tăng thì tăng `ram` |
| `MAX_PENDING_PER_USER` | false | false | false | `3` | Chỉnh được ở Cài đặt › Hệ thống |
| `JOB_STALL_MINUTES` | false | false | false | `8` | Đừng hạ dưới ~6 (`docs/DEPLOY.md`) |
| `JOB_TIMEOUT_MINUTES` | false | false | false | `180` | |
| `DEFAULT_TARGET_LANG` | false | false | false | `vi` | |

SMTP không bắt buộc: không có SMTP thì tài khoản mới dùng ngay, không xác nhận email, không có "Quên mật khẩu" (hệ quả bảo mật: `docs/KNOWN_ISSUES.md`). Cài đặt › Hệ thống ghi đè các biến SMTP.

**Không khai** (nội bộ / chỉ dev):

| Biến | Lý do |
|---|---|
| `DATA_DIR` | `Dockerfile` đặt `/data`; đổi thì mất khớp với điểm gắn ổ bền |
| `STATIC_DIR`, `UPSTREAM_ROOT` | `Dockerfile` đặt sẵn đường dẫn trong image |
| `WORKER_CMD`, `HANDOFF_WORKER_CMD` | lệnh worker dịch; chỉ E2E ghi đè bằng worker giả |
| `MAIL_DEV_LOG` | in link thư ra log — chỉ dev / E2E, không dùng khi deploy thật |
| `FORWARDED_ALLOW_IPS` | `Dockerfile` đặt `*`; cách proxy nền tảng xử lý `X-Forwarded-For`: **CHƯA BIẾT** |
| `SMTP_STARTTLS` | biến cũ, đã bỏ (thay bằng `SMTP_SECURITY`) |
| `HOME`, `PDF_TRANSLATE_MODEL`, `NOTO_FONT_PATH`, `PYTHONUNBUFFERED`, `PIP_NO_CACHE_DIR` | đặt trong `Dockerfile`; đổi `HOME` / `PDF_TRANSLATE_MODEL` làm mọi lượt dịch hỏng |

## 5. Cơ sở dữ liệu và ổ bền

- Cơ sở dữ liệu ngoài: **không khai** (SQLite nhúng, `/data/app.db`; migration alembic tự chạy lúc khởi động).
- Ổ bền: gắn **volume vào `/data`**. Form mẫu không có trường khai ổ bền (không có chữ "volume" ở mục 0–7 của `yc-deploy.html`); theo chủ dự án, nền tảng có lưu trữ bền — **cách gắn vào `/data` cần xác nhận với nền tảng** (CHƯA BIẾT).
- Không gắn: `/data` là volume vô danh của `VOLUME ["/data"]`, mất tài khoản + tệp khi redeploy hoặc khi container bị tạo lại; dữ liệu cũng mất khi Docker của máy chủ thử bị xoá (đã gặp 2026-10-06, `docs/KNOWN_ISSUES.md`).
- Quyền: image chạy bằng uid/gid 10001. Volume mới tạo từ image dùng được ngay; thư mục host thuộc root cần `chown -R 10001:10001` hoặc bật một lần bằng user 0 (README, "Lỗi thường gặp"). Nền tảng gắn ổ bền thuộc root-only thì container thoát với thông báo rõ: **CHƯA KIỂM trên Vibe Host**.
- Dung lượng `/data`: **CHƯA ĐO** (`docs/DEPLOY.md`: đo `du -sh /data/users` sau 2 tuần; chưa có hạn mức theo người dùng).

## 6. Tài khoản quản trị đầu tiên

| Trường | Giá trị |
|---|---|
| `setupPath` | `/setup` |
| Biến admin qua env | không có (tạo qua màn cài) |

- Cài mới: mở `/` → trình duyệt chuyển sang `/setup` (`frontend/src/App.test.tsx`: "sends public pages to /setup while the instance needs setup").
- `GET /` và `GET /setup` đều trả HTTP 200 (vỏ SPA, `backend/app/spa.py`) cả trước lẫn sau khi cài; việc chuyển trang diễn ra trong trình duyệt, không phải HTTP redirect. Nền tảng đọc `setupPath` bằng mã HTTP thì không phân biệt được "chưa cài" với "đã cài".
- Tín hiệu đọc được bằng máy: `GET /api/setup/status` (công khai, không cần đăng nhập) → `{"needs_setup": true|false, "setup_token_required": bool, "registration_open": bool, "mail_enabled": bool}` (`backend/app/system/setup.py`, `status_payload`). Cài mới: `"needs_setup": true`; cài xong: `false`.
- Ở `/setup`: nhập `SETUP_TOKEN`, email + mật khẩu quản trị; bước SMTP bỏ qua được. Người nhập đúng mã là quản trị viên.
- Chưa có ai: đăng ký / đăng nhập trả 409 `setup_required`. Cài xong: `POST /api/setup` trả 409 `setup_done` (`backend/app/system/setup_router.py`); mở lại trang `/setup` thì trình duyệt tự chuyển về `/` (`frontend/src/pages/SetupPage.tsx`: `<Navigate to="/" replace />` khi `needs_setup` false; E2E `golden-path.spec.ts` kiểm URL về `/`).
- Đóng đăng ký công khai sau khi cài: Cài đặt › Hệ thống.
- `SETUP_TOKEN` rỗng thì `/setup` không hỏi mã (`config.py`) — vì vậy mẫu khai `SETUP_TOKEN` là `required`.

## 7. Tệp cấu hình kèm theo

Không có. Mọi cấu hình đi qua biến môi trường (`backend/app/config.py`) và Cài đặt trong app.

## 9. Không cần nộp

`imageDigest`: tự động.

## Bằng chứng đã chạy thật

| Điều kiện của người duyệt | Trạng thái |
|---|---|
| Một lượt deploy thử thành công (link / ảnh chụp) | **CHƯA CÓ — nền tảng chạy thử sau khi nhận đề xuất** |
| Đăng nhập admin theo cách ở mục 6 trên Vibe Host | **CHƯA CÓ — nền tảng chạy thử sau khi nhận đề xuất** |
| Thời gian từ bấm deploy tới dùng được | **CHƯA CÓ — nền tảng chạy thử sau khi nhận đề xuất** |

Khi deploy thử, kiểm thêm (mẫu đi đường mặc định không đặt `APP_BASE_URL`, chưa từng chạy sau proxy thật của nền tảng):

- Sau `/setup`, Cài đặt › Hệ thống phải hiện tên miền `https` của nền tảng với nguồn "Ghi lại lúc cài đặt". Nếu trống: proxy không gửi `X-Forwarded-Proto: https` và app chạy chế độ không thư (liên kết trong thư bị tắt).
- Dịch thật ít nhất một tệp (chưa từng thành công ở đâu: Google trả 429 cho IP egress của máy chủ thử; khoá Gemini / Cloud chưa chạy với khoá thật).

Đã chạy ở nơi khác (không thay cho ba dòng trên):

| Việc | Ngày | Nguồn |
|---|---|---|
| Stack docker compose trên máy chủ thử, DB trống → `/setup` → `/health` 200; khởi động → `/health` 200 sau restart: 1,5 s | ngày không ghi trong tệp | `docs/MEASUREMENTS.md`, `docs/TEST_LOG.md` |
| E2E Playwright trên container thật, DB trống, worker dịch giả, kiểm không có yêu cầu tới bên thứ ba (phông tự host) | 2026-10-07 (`1 passed`, ≈ 1,2–1,3 phút) | `docs/TEST_LOG.md` (mục "E2E"), `e2e/` |
| Đo RAM/CPU pipeline tách + dựng, bảng dịch giả, offline | 2026-10-07 | `docs/MEASUREMENTS.md` |
| Dịch thật `google_free` đầu-cuối | **CHƯA TỪNG CHẠY ĐƯỢC** (Google trả 429 + captcha cho IP egress dùng chung của máy chủ thử) | `docs/MEASUREMENTS.md` |
| Dịch thật bằng khoá Gemini / Cloud Translation | **CHƯA VERIFY** (test dùng transport giả) | `docs/DEPLOY.md` "Việc còn treo", `docs/TEST_LOG.md` |

## Việc còn lại trước khi nộp

Chủ sở hữu / quản lý:
- [x] Repo `Mat-Bao-AI/MBC-TS-H-PDF-Translate`: fork công khai của upstream trong tổ chức (2026-10-08).
- [x] Mã dự án ở nhánh `pdf-translate-saas` (một commit sạch, không kèm lịch sử phát triển nội bộ; 2026-10-08).
- [ ] (Tuỳ chọn) Đặt nhánh mặc định của repo là `pdf-translate-saas` để trang repo hiện README của dự án thay vì README upstream.
- [x] `UPSTREAM_REPO` trong `Dockerfile` trỏ tới chính repo này: `main` chứa commit ghim `ae156cf…` (đã kiểm `git fetch` theo SHA qua HTTPS và commit là tổ tiên của `main`, 2026-10-08). Không xoá / viết lại `main`; "Sync fork" chỉ thêm commit nên an toàn. `NOTICE` và `README.md` ghi tác giả gốc `breslee1707/VI-Translate`.
- [ ] Quản lý duyệt AGPL-3.0 (`docs/DEPLOY.md`, "Việc còn treo").
- [ ] Nếu nền tảng build ở mỗi lượt deploy (§0): xác minh giấy phép model `doclayout.onnx` và phông GoNotoKurrent (đang **CHƯA XÁC MINH** trong `NOTICE`) trước khi nộp đường ảnh Docker.

Kỹ thuật:
- [ ] Chạy `docker build` đầy đủ từ `Dockerfile` (mới kiểm bản mỏng tương đương vì thiếu đĩa) rồi chạy lại các bước kiểm uid 10001 (`docs/TEST_LOG.md`, "Kiểm trong image").
- [ ] Dịch thật đầu-cuối ít nhất một tệp (khoá Gemini hoặc Cloud Translation).
- [ ] Kiểm trùng tên `PDF Translate` trên nền tảng.

Hỏi nền tảng:
- [ ] Build một lần cho mỗi mẫu hay ở mỗi lượt deploy của khách (§0); thời gian chờ build tối đa.
- [ ] Ổ bền gắn vào `/data` bằng cách nào (§5).
- [ ] Giá trị `generated` của `SECRET_KEY`: dài bao nhiêu ký tự, có giữ nguyên qua redeploy / restart không (§4); nếu ngắn hơn 32 hoặc đổi → `generated=false`.
- [ ] Nền tảng đánh giá `setupPath` thế nào: `/` và `/setup` đều trả 200; tín hiệu đọc được bằng máy là `GET /api/setup/status` (§6).
- [ ] Hạn mức thân yêu cầu của proxy so với `MAX_UPLOAD_MB` (50).
- [ ] `X-Forwarded-For`: proxy nối thêm hay ghi đè? Nếu chỉ nối thêm, khoá giới hạn tần suất theo IP giả mạo được.

Deploy thử trên Vibe Host:
- [ ] Bấm giờ từ lúc deploy tới dùng được; đăng nhập admin theo §6; kiểm Cài đặt › Hệ thống hiện tên miền `https` nguồn "Ghi lại lúc cài đặt"; dịch thật một tệp; chụp màn hình.
