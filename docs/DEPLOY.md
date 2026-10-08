# Triển khai — PDF Translate

Hướng dẫn tự triển khai trên máy chủ Docker bất kỳ hoặc nền tảng PaaS chạy container (Coolify, Dokploy, CapRover, Kubernetes…).
Image là một container duy nhất: web + hàng đợi dịch + SQLite nhúng, cổng `8000`, dữ liệu ở `/data`. Không cần cơ sở dữ liệu
ngoài. Bằng chứng đã chạy thật (ngày, lệnh, kết quả) nằm ở [TEST_LOG.md](TEST_LOG.md); số đo RAM/CPU ở
[MEASUREMENTS.md](MEASUREMENTS.md).

## Tóm tắt các bước

1. Dựng image ("Dựng image").
2. Đặt biến môi trường — tối thiểu `SECRET_KEY`, nên có `SETUP_TOKEN` ("Biến môi trường").
3. Gắn ổ bền vào `/data` ("Ổ lưu trữ bền cho `/data`") — làm TRƯỚC lần chạy đầu.
4. Đặt reverse proxy HTTPS phía trước ("Reverse proxy").
5. Mở địa chỉ → `/setup` tạo quản trị viên ("Cài đặt lần đầu và Cài đặt › Hệ thống").
6. Chạy các bước kiểm ("Kiểm sau khi triển khai").

## Dựng image

    docker build -t pdf-translate .

- Build lạnh đầy đủ đã đo ở 33 phút, image 2,69 GB (`TEST_LOG.md`, "Build đầy đủ"). Cần ≥ 12 GB đĩa trống trong lúc build.
- Cần mạng ra `github.com` (mã upstream ghim theo commit trong `Dockerfile`: `UPSTREAM_REPO` / `UPSTREAM_REF`), PyPI, npm và
  `huggingface.co` (model bố cục, qua `scripts/fetch_assets.py` của upstream).
- Nhiều nền tảng PaaS có kiểu build "Dockerfile": chỉ cần trỏ vào `Dockerfile` ở gốc repo. Chúng **bỏ qua** `docker-compose.yml`
  — `docker-compose.yml` chỉ dành cho chạy thử trên máy cá nhân; volume `app-data` trong đó không có tác dụng trên PaaS, nên
  phải khai ổ bền theo cách của nền tảng ("Ổ lưu trữ bền cho `/data`").
- `Dockerfile` cố ý không dùng tính năng chỉ có ở BuildKit (`COPY --chmod`…) và đặt quyền `/data` TRƯỚC dòng `VOLUME`: dựng được
  bằng cả builder cũ lẫn BuildKit. Dùng builder cũ (`docker build` không có buildx) thì mọi thay đổi trên `/data` sau dòng
  `VOLUME` của ảnh gốc bị bỏ — nếu dựng thêm một lớp lên trên image này, dùng BuildKit.

## Biến môi trường

Bảng đầy đủ (khoá, bắt buộc, bí mật, mặc định, ghi chú) nằm ở một nơi: [VIBEHOST.md](VIBEHOST.md) §4. Tối thiểu:

    export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')   # ≥ 32 ký tự, GIỮ LẠI
    export SETUP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')  # mã cài đặt, đưa riêng cho người cài

- `SECRET_KEY`: thiếu hoặc ngắn hơn 32 ký tự thì app không khởi động. Xem "Đổi `SECRET_KEY`" trước khi đổi giá trị.
- `SETUP_TOKEN`: không bắt buộc với app, nhưng **nên đặt** cho mọi instance mở ra Internet — xem "Cài đặt lần đầu". Cài xong có
  thể xoá.
- `APP_BASE_URL`, `SOURCE_URL`, `SMTP_*`, hạn mức: tuỳ chọn.
- Nền tảng PaaS đọc env của app trực tiếp, không qua `docker-compose.yml`.

## Ổ lưu trữ bền cho `/data`

Toàn bộ dữ liệu (DB `app.db`, tệp người dùng, `runner.lock`) nằm ở `/data`. `VOLUME ["/data"]` trong `Dockerfile` chỉ sinh **volume
vô danh mới cho mỗi container** → mỗi lần triển khai lại, hoặc bật lại container đã bị tạo lại, là DB trống: mất hết tài khoản và
tệp. Vì vậy **bắt buộc** gắn ổ bền (volume có tên hoặc thư mục host) vào `/data`:

- `docker run`: `-v pdf-translate-data:/data`.
- Compose: `volumes: [app-data:/data]` (đã có trong `docker-compose.yml`).
- PaaS: thêm Persistent Storage / Volume, đích **`/data`**. Mỗi nền tảng một cách; cần kiểm lại sau lần triển khai đầu.

Kiểm ("Dữ liệu sống qua triển khai lại"): tạo tài khoản, tải một tệp, triển khai lại, đăng nhập lại. Đăng nhập báo sai mật khẩu
hoặc danh sách trống nghĩa là `/data` chưa được gắn ổ bền.

## Chạy bằng user thường (uid 10001)

Image chạy bằng user `app` (uid/gid **10001**), không phải root; `HOME=/home/app` (cache của babeldoc / upstream nằm ở
`/home/app/.cache`). `docker-entrypoint.sh` kiểm `$HOME/.cache`, `/data`, `/data/app.db*` và `/data/users` ghi được trước khi
chạy app — thiếu quyền thì container thoát mã 1 kèm cách sửa, thay vì `/health` vẫn 200 mà mọi lượt dịch / lượt ghi hỏng.

- **Chỉ hỗ trợ uid 10001 (mặc định) hoặc user 0.** `--user` khác (vd `--user 12345`, `user: "1000"`) không vào được `/home/app`
  (0700) → container dừng ngay với thông báo "chỉ hỗ trợ uid 10001 … hoặc user 0": bỏ `--user` / `user:`.
- **Volume có tên mới** (volume tạo mới từ image, `app-data` của `docker-compose.yml`): chạy ngay — Docker chép quyền `app` của
  `/data` trong image sang volume còn trống.
- **Thư mục host thuộc root** (bind mount, Storage kiểu Directory) hoặc **volume do image cũ (chạy root) đã ghi**: container
  thoát mã 1 với thông báo `LỖI: tiến trình app (uid=10001 gid=10001) không ghi được vào /data …`. Sửa MỘT lần, chọn một:
  - `sudo chown -R 10001:10001 <thư mục trên host>`, rồi bật lại như thường;
  - **dừng container cũ (chạy root) đang dùng thư mục đó trước**, rồi bật container mới một lần bằng user 0
    (`docker run --user 0 …`, `user: "0"` trong compose): entrypoint `chown` thư mục / symlink / tệp thường chưa thuộc 10001
    trong `/data` (không vượt sang hệ tệp khác; tệp có liên kết cứng hoặc tệp đặc biệt thì bỏ qua và in số lượng), hạ quyền hẳn
    (`setpriv`: bỏ mọi capability, `no_new_privs`) rồi chạy lại đúng các bước kiểm của uid 10001 — app vẫn chạy bằng 10001
    (kiểm: `docker exec <container> grep Uid /proc/1/status` ra `10001`). Sau đó bỏ user 0. Entrypoint từ chối khi `DATA_DIR`
    (sau khi giải symlink) là `/` hoặc nằm trong thư mục hệ thống (`/app`, `/etc`, `/usr`, `/var`…).
- Image không còn tệp setuid/setgid; `docker-compose.yml` và `e2e/compose.fresh.yml` đặt `security_opt: no-new-privileges:true`.
  Nên đặt tương đương trên nền tảng của bạn nếu có.

## Reverse proxy

Phía trước cần một reverse proxy HTTPS (Traefik, Caddy, nginx, bộ cân bằng tải của nền tảng…). Không publish cổng 8000 ra
Internet trực tiếp. `docker-compose.yml` chỉ mở `127.0.0.1:18081` cho chạy thử.

- **TLS.** Cookie phiên đặt `Secure`: `http://` chỉ chạy được trên `localhost` / `127.0.0.1`.
- **`X-Forwarded-Proto`.** Proxy phải gửi `X-Forwarded-Proto: https`. App dùng nó để ghi lại địa chỉ trang lúc `/setup` (xem
  "Địa chỉ trang trong thư"); thiếu header này thì địa chỉ không được ghi (chỉ ghi khi là https, hoặc http trên localhost /
  127.0.0.1), thư có liên kết bị tắt.
- **`X-Forwarded-For` và `FORWARDED_ALLOW_IPS`.** Giới hạn đăng nhập sai / đăng ký theo IP lấy IP thật từ `X-Forwarded-For`.
  `Dockerfile` đặt `FORWARDED_ALLOW_IPS="*"` (tin mọi nguồn) — chỉ an toàn khi proxy **ghi đè** `X-Forwarded-For` do client gửi.
  Nếu proxy chỉ nối thêm, client giả được IP để lách giới hạn. Kiểm bằng "Kiểm giả mạo X-Forwarded-For" dưới đây; không đạt thì
  đặt env `FORWARDED_ALLOW_IPS` = IP/dải mạng của proxy (vd dải của network Docker mà proxy gắn vào, lấy bằng
  `docker network inspect`), không cần build lại.
- **Cỡ thân yêu cầu.** Giới hạn thân yêu cầu của proxy phải **≥ `MAX_UPLOAD_MB`** (mặc định 50 MB), nếu không tệp lớn bị proxy cắt
  trước khi tới app (nginx: `client_max_body_size`; Traefik: middleware `buffering`; nhiều PaaS có ô cấu hình riêng).
- **Kiểm sức khoẻ.** `GET /health` (không cần đăng nhập) trả 200 `{"status":"ok","queue":0}`; image có sẵn `HEALTHCHECK`. Nếu
  nền tảng tự kiểm bằng `curl` bên trong container thì `curl` đã có sẵn trong image. Phân biệt lỗi proxy: 404 bắt-tất = chưa có
  router; "no available server" = container chưa chạy / chưa healthy; 502 = proxy trỏ sai cổng (phải là 8000).

## Cài đặt lần đầu và Cài đặt › Hệ thống

**Trình cài đặt `/setup`.** DB chưa có tài khoản nào → mọi đường dẫn về `/setup`, `register` / `login` trả 409 `setup_required`.
Bước 1 tạo **tài khoản quản trị** (đã xác nhận email, đăng nhập luôn); bước 2 cấu hình SMTP hoặc "Bỏ qua". Có người dùng rồi thì
`/setup` đóng (409 `setup_done`; hai người gửi cùng lúc thì đúng một người thành). Nâng một instance đang có người dùng lên
migration `0005`: người tạo tài khoản **sớm nhất** thành quản trị viên. Chưa có trang / API cấp quyền quản trị (ngoài phạm vi) —
quản trị viên duy nhất không xoá được tài khoản khi còn người khác (409 `last_admin`).

**`SETUP_TOKEN` (khuyến nghị cho app công khai).** Từ lúc triển khai tới lúc chủ instance chạy `/setup`, ai mở link trước là
thành quản trị viên. Có env `SETUP_TOKEN` thì bước 1 đòi "Mã cài đặt" (so thời gian hằng; sai → 403 `invalid_setup_token`); mỗi
lượt `POST /api/setup` tính vào hạn mức 10 lượt / 15 phút / IP chung với đăng ký. Sinh mã ngẫu nhiên, đưa riêng cho người cài
(không dán vào kênh chung); cài xong có thể xoá env.

**Cài đặt lần đầu** (ngay khi `/health` lên, TRƯỚC khi đưa link cho ai): mở địa chỉ → tự chuyển tới `/setup` → nhập Mã cài đặt +
tên / email / mật khẩu quản trị → bước "Gửi thư (SMTP)": nhập rồi "Gửi thư thử", hoặc "Bỏ qua". Kết quả mong đợi: về trang chủ
"Xin chào, …"; mở lại `/setup` thì về `/`; menu avatar có mục "Hệ thống".

**SMTP là tuỳ chọn.** Chưa có SMTP (không cấu hình trong Cài đặt, không `SMTP_HOST`, không `MAIL_DEV_LOG`): đăng ký tạo tài khoản đã
xác nhận (dùng ngay, không tự đăng nhập); quên mật khẩu / gửi lại thư / đổi email trả 409 `mail_not_configured`, trang tương ứng
báo "Máy chủ chưa cấu hình gửi thư"; quản trị viên thấy dải "Chưa cấu hình SMTP" ở mọi trang. Tài khoản **chưa xác nhận** từ thời
còn SMTP vẫn bị chặn đăng nhập tới khi có SMTP lại. Chế độ này để lộ email nào đã có tài khoản (đăng ký rồi thử đăng nhập) — app
công khai nên có SMTP (`KNOWN_ISSUES.md`). Có thông tin SMTP thì nhập ở **Cài đặt › Hệ thống** (ghi đè env, có hiệu lực ngay).

**Địa chỉ trang trong thư (`APP_BASE_URL`, tuỳ chọn từ migration 0007).** Địa chỉ này chỉ dùng dựng link trong thư (xác nhận
email, đặt lại mật khẩu, đổi email). Thứ tự ưu tiên: env `APP_BASE_URL` (nếu đặt) → địa chỉ **ghi lại lúc chạy `/setup`**
(`instance_settings.site_url`: gốc `scheme://máy[:cổng]` của chính request tạo quản trị viên, scheme theo `X-Forwarded-Proto`
của proxy; chỉ ghi khi là https, hoặc http trên localhost / 127.0.0.1) → chưa biết. Địa chỉ đã ghi **không bao giờ tự đổi** (kể cả
khi `/setup` mở lại vì instance trống, hay khi gắn tên miền riêng): muốn đổi thì đặt `APP_BASE_URL` rồi khởi động lại. Chưa biết
địa chỉ thì thư có liên kết **tắt** như khi chưa có SMTP (đăng ký dùng ngay, quên mật khẩu / đổi email 409 `mail_not_configured`);
"Gửi thư thử" vẫn chạy. Instance cài trước 0007 chưa có địa chỉ ghi lại — giữ `APP_BASE_URL`. Link không bao giờ dựng từ Host của
request thường (chống đầu độc Host header vào thư đặt lại mật khẩu). Cài đặt › Hệ thống, thẻ SMTP, hiện địa chỉ đang dùng và
nguồn của nó.

**Cài đặt › Hệ thống** (`/settings/system`, chỉ quản trị viên — người thường gõ URL về tab Tài khoản, API 403 `admin_required`):
- **Dải nhắc "Chưa cấu hình SMTP".** Quản trị viên bấm × để đóng vĩnh viễn: lựa chọn lưu trên máy chủ theo tài khoản
  (`users.smtp_notice_dismissed`, migration 0006), mọi trình duyệt/thiết bị đều không hiện lại.
- **Gửi thư (SMTP).** Nguồn giải **lúc gửi**, thứ tự cố định: cấu hình lưu trong Cài đặt → env `SMTP_*` → `MAIL_DEV_LOG=1` → chỉ in
  ra log (= "chưa cấu hình"). Lưu trong Cài đặt **ghi đè env**, có hiệu lực cho thư kế tiếp, không cần khởi động lại; "Xoá cấu
  hình, quay về biến môi trường" trả nguồn về env / log. "Gửi thư thử" gửi tới email của chính quản trị viên bằng giá trị đang gõ
  (chưa lưu), tối đa 6 lượt/phút. Bảo mật: `STARTTLS` (thường 587), `SSL/TLS` (465, TLS ngầm định), `Không` — env tương ứng
  `SMTP_SECURITY=starttls|ssl|none` (`SMTP_STARTTLS=0` cũ = `none`). Mật khẩu SMTP mã hoá AES-GCM như API key (HKDF info
  `instance-settings/v1`), không bao giờ trả về / vào log: **đổi `SECRET_KEY` thì mật khẩu đã lưu không đọc được** (thẻ báo "nhập
  lại", thư gửi không đăng nhập SMTP và lỗi chỉ vào log). Máy chủ SMTP do quản trị viên nhập là điểm SSRF tiềm ẩn (trỏ được tới
  host nội bộ, cổng bất kỳ): chấp nhận vì chỉ quản trị viên đặt được, kết nối chỉ là bắt tay SMTP có hạn 15 s, lỗi trả về chỉ gồm
  tên lớp + thông điệp `smtplib` cắt 200 ký tự.
- **Chứng chỉ TLS của máy chủ SMTP được kiểm** (chuỗi CA + tên máy, `ssl.create_default_context()`) cho cả `STARTTLS` lẫn
  `SSL/TLS`: máy chủ dùng chứng chỉ tự ký / CA nội bộ **không gửi được** (`SSLCertVerificationError` trong "Gửi thư thử" / log) —
  chưa có tuỳ chọn bỏ kiểm; dùng máy chủ có chứng chỉ công khai hợp lệ.
- **Mật khẩu đã lưu chỉ dùng lại cho đúng máy chủ.** Để trống ô mật khẩu = dùng mật khẩu đang có (trong Cài đặt, hoặc
  `SMTP_PASSWORD` env khi form điền sẵn từ env) **chỉ khi** máy chủ + bảo mật trong form trùng nguồn đó; đổi một trong hai thì
  phải nhập lại (có tên đăng nhập mà không có mật khẩu dùng được → 422 `invalid_smtp`, ô mật khẩu). Lưu form điền sẵn từ env với
  ô mật khẩu trống là **chép** `SMTP_PASSWORD` (mã hoá) vào DB: từ đó **đổi `SMTP_PASSWORD` trong env không có tác dụng** cho tới
  khi bấm "Xoá cấu hình, quay về biến môi trường" (hoặc nhập mật khẩu mới trong Cài đặt).
- **Đăng ký & hàng chờ.** Công tắc "Cho phép đăng ký tài khoản mới" (tắt → `/register` báo đóng, API 403 `registration_closed`).
  "Số tệp chờ tối đa mỗi người" 1–100 **ghi đè** `MAX_PENDING_PER_USER`, đọc mỗi lần tải lên / dựng lại / dịch lại; "Đặt về mặc
  định" quay về env. Chỉ có **một** luồng dịch (`MAX_CONCURRENT_JOBS=1`) và chưa có xoay vòng giữa người dùng: hạn cao trên máy
  dùng chung thì một người dịch lại hàng loạt là người khác đợi hết lượt.

**`MAIL_DEV_LOG=1`** — chỉ cho dev / E2E: thư in ra log nhưng **tính là đã cấu hình** (xác nhận email vẫn bắt buộc, link đọc từ
log). Không đặt cho bản triển khai thật.

**Dịch lại** (↻ ở mọi dòng của bảng, nút "Dịch lại" ở trang chi tiết, "Dịch lại" ở thanh chọn nhiều tệp — kể cả "Chọn tất cả N
tệp"): tệp đã xong dịch lại **từ đầu** (gọi lại dịch vụ dịch — tốn lượt gọi API với Gemini / Cloud), bản cũ vẫn xem / tải được tới
khi bản mới xong; lỗi thì giữ bản cũ kèm lý do. Tệp lỗi dịch lại tại chỗ (giữ ngôn ngữ / chế độ / model thì các đoạn đã dịch được
dùng lại). Hàng loạt bỏ qua tệp đang chờ / đang dịch và tệp vượt hạn chờ, báo số. `POST /api/files/{id}/retry` đã bỏ (thay bằng
`/retranslate` + `/bulk-retranslate`).

## Đổi `SECRET_KEY`

API key Gemini / Google Cloud của người dùng được mã hoá AES-GCM bằng khoá dẫn từ `SECRET_KEY` (HKDF-SHA256, info
`api-credentials/v1`); mật khẩu SMTP đã lưu cũng vậy (info `instance-settings/v1`). **Đổi `SECRET_KEY` là mọi key / mật khẩu đã
lưu không giải mã được nữa:** app coi như người dùng chưa nhập key (Cài đặt hiện "Chưa có key", tải lên bằng engine đó báo
`missing_api_key`, tệp đang chờ dùng engine đó lỗi với hướng dẫn thêm key lại); thư không đăng nhập được SMTP cho tới khi nhập lại
mật khẩu. Không mất dữ liệu gì khác — tài khoản, mật khẩu đăng nhập và tệp không bị ảnh hưởng; người dùng dán lại key là xong. Vì
vậy: không xoay `SECRET_KEY` tuỳ tiện; nếu bắt buộc, báo trước cho người dùng. Key không bao giờ ra log/argv — chỉ đi qua biến môi
trường của tiến trình worker con.

## Font bản dịch

Chữ của bản dịch dựng bằng **Liberation Sans / Liberation Serif đủ 4 kiểu thật** (gói `fonts-liberation` đã có trong image,
`/usr/share/fonts/truetype/liberation/`). Người dùng chọn `Tự động (theo bản gốc)` / `Không chân` / `Có chân` ở Cài đặt › Dịch
thuật, lúc tải lên, hoặc "Dựng lại với font khác" ở trang chi tiết (Gemini / Cloud: dùng lại bảng đoạn đã dịch, không gọi API;
Google miễn phí: dịch lại từ đầu). Cách áp: tiến trình worker gán đè ba tên của upstream — `pdf2zh.high_level.download_remote_fonts`,
`pdf2zh.high_level.output_style_font_paths`, `pdf2zh.converter.BASE14_STYLE_FONTS` — sau một bước kiểm tra cứng. **Không sửa
upstream, không sửa `worker.py`**: `WORKER_CMD` mặc định là `app/engine/font_worker.py` (bọc `worker.py`); image `:e2e` ghi đè
bằng worker giả.

**Nâng pin upstream (`UPSTREAM_REF` trong Dockerfile):** ba tên trên là hợp đồng ngầm. Build xong, **BẮT BUỘC** chạy

    docker run --rm --network none -v "$PWD/scripts:/work/scripts:ro" pdf-translate \
        python -W "ignore:builtin type swig:DeprecationWarning" /work/scripts/font-render-check.py

và chỉ dùng image khi in `FONT RENDER CHECK: PASSED` (0 toán tử viền `2 Tr`, 0 đoạn sót, font Liberation được nhúng, subset chạy
được và không đổi điểm ảnh nào). Bước này không thay thế được bằng kiểm tra hook: kiểm tra cứng chỉ thấy tên/kiểu của hook còn đó,
không thấy được việc upstream refactor đến mức không còn gọi các hàm đã gán đè — chỉ dựng thật mới lộ ra (chữ viền `2 Tr` quay
lại). Upstream đổi tên/kiểu một hook → job lỗi rõ `font_profile_unsupported` ("Không áp được font cho bản dịch vì nhân dịch đã
thay đổi…"): sửa `backend/app/engine/fonts.py` cho khớp, không bao giờ bỏ kiểm tra cứng.

**Job lỗi `font_profile_unsupported` / `font_files_missing` — xem ở đâu:** `worker-stderr.log` trong thư mục job
(`/data/users/<user>/<file>/`, lượt dựng lại lỗi giữ thành `rebuild-stderr.log`) có đúng MỘT dòng
`font_profile code=<mã> detail=<chi tiết>`. `detail` thường gặp: `import:ModuleNotFoundError:pdf2zh.high_level` (không nạp được
module upstream), `hook:BASE14_STYLE_FONTS:missing` (upstream bỏ/đổi tên hook), `files:sans:BoldItalic` (thiếu tệp font của hồ sơ
— kiểm gói `fonts-liberation`), `error:<Class>` (lỗi khác).

Dung lượng: upstream nhúng nguyên 4 font (~+650 KB/tệp); worker subset lại font sau khi dựng. Thí nghiệm subset đạt: text từng
trang và pixel giống hệt, tệp nhỏ hơn ~35% ở thí nghiệm lúc viết kế hoạch (1.022.745 → 665.101 B) và ~43% ở lần kiểm trong image
(`font-render-check.py`: 871.312 → 496.090 B). Worker vẫn kiểm lại cho từng tệp (chỉ thay khi text giống hệt và tệp nhỏ hơn) và bỏ
qua tài liệu ≥ 200 trang.

**Dựng lại thất bại** không làm mất gì: bản dịch cũ vẫn tải được (trạng thái `done`, `rebuild_error` giữ thông điệp), và các đoạn
đã dịch (trả tiền) vẫn nằm trong `segments.jsonl`. **Gỡ model Gemini:** job lỗi `model_unavailable` → model bị bỏ khỏi danh sách
của key; nếu là mặc định thì chuyển sang Flash-Lite / model đầu tiên còn lại / Google miễn phí (xem `KNOWN_ISSUES.md`).

**Engine nào chạy thật với image `:e2e`** (chỉ đè `WORKER_CMD`, không đè `HANDOFF_WORKER_CMD`; dùng cho E2E, xem
[DEVELOPMENT.md](DEVELOPMENT.md)):

| Engine | Trên image `:e2e` | Ghi chú |
|---|---|---|
| `google_free` ("Dịch thuần · Google miễn phí") | **worker giả** (`/app/e2e-fake-worker.py`) — chép nguyên tệp, không dịch | dùng cho E2E; không phát dòng font → trang chi tiết không ghi font |
| `google_cloud`, `gemini` (cần key) | **lõi upstream thật + gọi Google thật** qua `app/engine/handoff_worker.py` | tốn tiền theo key của người dùng; dựng bằng font Liberation, có "Dựng lại với font khác" |

Chẩn đoán khi lỗi: thông điệp lỗi của tệp nói rõ nguyên nhân (key sai, API chưa bật, chưa bật thanh toán, key bị giới hạn, giới hạn
tốc độ, hết hạn mức ngày, model không còn, dịch vụ từ chối); chi tiết kỹ thuật nằm trong `worker-stderr.log` của thư mục job, dạng
`provider=… http=… status=… reason=…` — không có key, không có văn bản tài liệu. Bảng đoạn đã dịch (`segments.jsonl` +
`segments.meta.json`) nằm cùng chỗ: "Dịch lại" sau lỗi chỉ dịch (và trả tiền) phần còn thiếu.

## Kiểm sau khi triển khai

**Chạy smoke** (`scripts/smoke.sh` tự đọc `/api/setup/status`; chưa chạy `/setup` thì script dừng, báo mở `/setup` trước):
- **Đã nhập SMTP thật**: link xác nhận của tài khoản smoke đi qua email tới `smoke-<giờ>@example.com`, **không** vào log → đặt
  `SMOKE_EMAIL`/`SMOKE_PASSWORD` của một tài khoản đã xác nhận (vd quản trị viên vừa tạo; truyền qua env, không ghi vào tệp). Cũng
  dùng cách này khi đăng ký đang đóng.
- **Bỏ qua SMTP**: tài khoản smoke dùng ngay, không cần link, không cần `LOGS`.
- `LOGS` (lệnh in log của app) chỉ cần với `MAIL_DEV_LOG=1` — chế độ dev / E2E, không bật trên bản triển khai thật.

      read -rs SMOKE_PASSWORD && export SMOKE_PASSWORD                         # mật khẩu không vào history / argv
      BASE="https://<địa chỉ trang>" SMOKE_EMAIL="<email quản trị>" scripts/smoke.sh e2e/fixtures/sample-2p.pdf   # có SMTP thật
      BASE="https://<địa chỉ trang>" scripts/smoke.sh e2e/fixtures/sample-2p.pdf                                  # bỏ qua SMTP

Kết quả mong đợi: `OK: dịch xong …`. Nếu lỗi `PDFValueError: Failed to translate` thì máy chủ của bạn bị Google chặn egress
(endpoint miễn phí trả 429 + captcha cho IP dùng chung): **dừng, không mở cho người dùng** (mọi job dùng engine miễn phí sẽ lỗi);
chọn nhân dịch khác (khoá Gemini / Cloud Translation của người dùng) hoặc đổi egress. Lỗi khác thì xem cổng / nhãn của proxy.

**Kiểm giả mạo X-Forwarded-For** (giới hạn đăng nhập sai theo IP chỉ có nghĩa khi proxy ghi đè header này của client):

    for i in 1 2 3 4 5 6; do
      curl -s -o /dev/null -w '%{http_code} ' -X POST "https://<địa chỉ trang>/api/auth/login" \
        -H 'X-Requested-With: fetch' -H 'Content-Type: application/json' \
        -H "X-Forwarded-For: 203.0.113.$i" -d '{"email":"xff-check@example.com","password":"sai-mat-khau"}'
    done; echo

Kết quả mong đợi: `401 401 401 401 401 429` (chạy lại trong vòng 15 phút thì đổi email). Nếu lần thứ 6 vẫn `401`: proxy đang
chuyển nguyên `X-Forwarded-For` của client và container tin mọi nguồn (`FORWARDED_ALLOW_IPS="*"`) → đặt env `FORWARDED_ALLOW_IPS`
= IP/dải mạng của proxy ("Reverse proxy"), triển khai lại, kiểm lại tới khi ra `429`. (Giới hạn 20 lần sai / 15 phút cho mỗi email
vẫn chặn được dù IP bị giả, nhưng không thay được bước này.)

**Dữ liệu sống qua triển khai lại**: đăng ký một tài khoản trên trang web, tải lên một tệp, triển khai lại (hoặc
`docker rm` container rồi chạy lại với cùng volume), đợi `/health` lên, rồi đăng nhập lại bằng đúng tài khoản đó. Kết quả mong
đợi: đăng nhập được và "Tệp của tôi" còn đúng tệp vừa tải. Sai mật khẩu / danh sách trống = `/data` chưa được gắn ổ bền.

**Checklist trước khi mở cho người dùng**

- [ ] Ổ bền gắn vào `/data`; "Dữ liệu sống qua triển khai lại" đạt.
- [ ] Kiểm giả mạo X-Forwarded-For: lần thứ 6 là `429`.
- [ ] Giới hạn thân yêu cầu của proxy ≥ `MAX_UPLOAD_MB`.
- [ ] Smoke nhân dịch ra `OK: dịch xong` — **cổng đi/không đi** với engine miễn phí (xem trên).
- [ ] `SETUP_TOKEN` đã đặt và `/setup` đã chạy xong — trước đó link chưa đưa cho ai.
- [ ] SMTP thật đã nhập ở Cài đặt › Hệ thống và "Gửi thư thử" tới được hộp thư — hoặc chấp nhận chế độ không thư (tài khoản mới
      dùng ngay, không có quên mật khẩu / đổi email).
- [ ] Cài đặt › Hệ thống hiện địa chỉ `https` đúng với nguồn "Ghi lại lúc cài đặt" (hoặc đặt `APP_BASE_URL`).
- [ ] Giấy phép: đã đặt `SOURCE_URL` trỏ tới mã nguồn công khai của bản đang chạy (AGPL-3.0 §13; `LICENSE`, `NOTICE`).

## Sao lưu, khôi phục, nâng cấp, lùi bản

Ví dụ dưới dùng container `pdf-translate`, volume `pdf-translate-data`, image `pdf-translate` như trong
[README](../README.md#lệnh-dựng--chạy); đổi tên cho khớp cách bạn chạy. Chi tiết lệnh nâng cấp và lùi bản: README, mục "Nâng cấp &
lùi bản".

- **Sao lưu**: dừng container (SQLite không ghi dở) rồi nén `/data`:

      docker stop pdf-translate
      docker run --rm --user 0 -v pdf-translate-data:/data:ro -v "$PWD":/backup --entrypoint tar pdf-translate \
        czf /backup/pdf-translate-data-$(date +%Y%m%d-%H%M).tgz -C /data .

- **Nâng cấp** = dựng lại image từ mã mới (hoặc đổi tag / git ref), dừng container cũ, chạy lại với **cùng volume `/data` và cùng
  `SECRET_KEY`**. Giữ image cũ bằng `docker tag pdf-translate pdf-translate:prev` TRƯỚC khi dựng lại.
- **Migration chạy tự động** lúc khởi động (`upgrade_db` → alembic `head`). Mỗi lần nâng revision, DB mới **không** chạy được
  với image cũ: image cũ ném `Can't locate revision identified by '<revision>'`, lifespan lỗi, app không khởi động (và
  `restart: on-failure` làm nó khởi động lại liên tục). Vì vậy **luôn sao lưu `/data` trước khi bật image mới**.
- **Lùi bản** có hai cách, đều cần image cũ còn giữ:
  - (a) Khôi phục bản sao lưu trước nâng cấp (mất mọi thay đổi từ lúc nâng cấp):

        docker stop pdf-translate && docker rm pdf-translate
        export BACKUP=$(ls -t pdf-translate-data-*.tgz | head -1)
        docker run --rm --user 0 -e BACKUP -v pdf-translate-data:/data -v "$PWD":/backup:ro --entrypoint sh pdf-translate \
          -c 'find /data -mindepth 1 -delete && tar xzf "/backup/$BACKUP" -C /data'
        # rồi chạy image CŨ (pdf-translate:prev) với đúng volume và SECRET_KEY cũ

  - (b) Hạ cấp DB bằng chính image **mới** (giữ tài khoản / tệp, chỉ bỏ các cột / bảng của revision mới). Chờ hàng đợi rỗng
    trước (`/health` → `"queue":0`): một job còn chờ có thể chạy trên image cũ không đúng ý. Backend không có `alembic.ini`
    (migration chạy bằng code trong `app/db.py`) nên lệnh trần `alembic downgrade` **không** chạy được — dùng đúng lệnh này (thư
    mục làm việc của image là `/app/backend`, DB ở `/data/app.db` theo `DATA_DIR` mặc định), thay `<revision>` bằng revision muốn
    về:

        docker stop pdf-translate
        docker run --rm -v pdf-translate-data:/data pdf-translate python -c \
          "from alembic import command; from alembic.config import Config; from app.db import MIGRATIONS; \
        c = Config(); c.set_main_option('script_location', str(MIGRATIONS)); \
        c.set_main_option('sqlalchemy.url', 'sqlite:////data/app.db'); command.downgrade(c, '<revision>')"

    Hạ cấp xuống `0004` bỏ cấu hình trong Cài đặt › Hệ thống (SMTP, công tắc đăng ký, hạn chờ), cờ quản trị và các yêu cầu dịch
    lại đang dở; xuống `0003` bỏ thêm tên hiển thị, font, `new_email`… Sau đó bật image cũ và kiểm
    `select version_num from alembic_version` ra đúng revision.
- Không bao giờ xoá volume (`docker volume rm`, `docker compose down -v`) trên stack đang có dữ liệu thật.
- Bộ nhớ đệm bản dịch của upstream nằm ở `/home/app/.cache/pdf2zh/cache.v1.db` trong container (ngoài `/data`; babeldoc còn có thư
  mục riêng `/home/app/.cache/babeldoc/`): không được giữ qua việc tạo lại container, không nằm trong số đo `du -sh /data`, và
  còn giữ văn bản của tài liệu đã xoá chừng nào container còn sống.

## Giới hạn tần suất

Đếm trong RAM của tiến trình, mất khi khởi động lại; vượt hạn mức trả 429.

| Hành động | Hạn mức |
|---|---|
| Đăng nhập sai | 5 lần / 15 phút cho một cặp IP + email (cần proxy ghi đè `X-Forwarded-For`, xem "Reverse proxy"), 20 lần / 15 phút cho một email bất kể IP |
| `POST /api/setup`, đăng ký, quên mật khẩu, gửi lại thư | 10 lượt / 15 phút / IP |
| Lưu API key (`PUT /api/settings/credentials/{provider}`) | 10 lần / 15 phút mỗi tài khoản và 20 lần / 15 phút mỗi IP (mọi lượt đều tính, kể cả key sai); trả `too_many_requests` |
| "Gửi thư thử" (SMTP) | 6 lượt / phút |

Bộ đếm nằm trong từng tiến trình: chạy uvicorn với `--workers N` thì hạn mức thực tế nhân N (image chạy một worker).

## Việc còn treo

- **Gemini / Cloud Translation thật CHƯA VERIFY** — toàn bộ test dùng transport giả; cần một key thật (AI Studio hoặc Google
  Cloud) để dịch thử 1 tệp qua Cài đặt → tải lên "Dịch bằng AI". Rủi ro đã biết: định dạng `responseSchema` của Gemini, cách Cloud
  Translation (format html) giữ thẻ `<bN>`.
- **Bản dịch thật chưa verify đầu-cuối bằng engine miễn phí**: endpoint dịch miễn phí của Google (`translate.google.com/m`) trả
  captcha (HTTP 429) cho IP egress dùng chung của môi trường thử, xác nhận độc lập bằng `curl` từ cả máy chủ lẫn container, thử lại
  3 lần thật trải trong ~20 phút, mỗi lần đều bị chặn (`MEASUREMENTS.md`). Việc đầu tiên cần verify trên một máy chủ có egress khác
  là `scripts/smoke.sh` ở "Kiểm sau khi triển khai".
- Job handoff chạy lõi **hai lượt** (tách đoạn + dựng PDF) → phân tích bố cục tốn gấp đôi thời gian so với `google_free`;
  `JOB_STALL_MINUTES` được làm mới theo từng dòng tiến độ của cả 3 bước. Ở bước dịch, mỗi lô xong mới có một dòng tiến độ; một
  request xấu nhất (thử lại + hết giờ 10 s/120 s) bị chặn ở ~310 s — đừng hạ `JOB_STALL_MINUTES` xuống dưới ~6. **Mức chặn đó là
  theo request, không theo lô**: lô nào Gemini trả sai (JSON hỏng / sai số đoạn) bị chia đôi đệ quy — tới ~79 request nối tiếp cho
  lô 40 đoạn, không có dòng tiến độ nào ở giữa — nên với model chậm (vd 3.1 Pro) job vẫn có thể bị giết vì "đứng" sau 8 phút, và
  "Dịch lại" trả tiền lại cả lô đó (bảng đoạn chỉ lưu theo lô gốc). Xem `KNOWN_ISSUES.md`.
- **Chưa có nút huỷ job đang chạy bằng key trả phí**: xoá key trong Cài đặt KHÔNG dừng job đang dịch (worker đã nhận key qua env
  lúc bắt đầu) — job chạy tới hết và vẫn tính tiền theo key đó. Chỉ job còn chờ mới lỗi "Chưa có API key…". Cần nút huỷ (giết
  worker + đánh dấu lỗi) trước khi mở rộng.
- **AGPL-3.0 §13**: người vận hành cho người ngoài truy cập qua mạng phải cung cấp mã nguồn của bản đang chạy (giấy phép của lõi
  upstream). Đã có `LICENSE` (AGPL-3.0) và `NOTICE` ở gốc repo; đặt `SOURCE_URL` trỏ tới kho mã công khai.
- Phông giao diện Be Vietnam Pro (OFL-1.1) được đóng gói trong image (`@fontsource/be-vietnam-pro`); trang không còn yêu cầu phông
  của bên thứ ba (E2E kiểm).
- **`/data` phải là ổ bền** ("Ổ lưu trữ bền cho `/data`") — không làm là mất sạch dữ liệu ở lần triển khai lại.
- **Giả mạo X-Forwarded-For**: tuỳ proxy có ghi đè header này hay không — kiểm theo "Kiểm giả mạo X-Forwarded-For"; nếu không,
  thu hẹp `FORWARDED_ALLOW_IPS` về IP của proxy.
- **Dockerfile đầy đủ chưa build lại sau khi đổi sang user thường** (đĩa của môi trường thử không đủ) — bản dựng tương đương đã
  kiểm (`TEST_LOG.md`); dựng đầy đủ khi còn ≥ 12 GB đĩa trống rồi chạy lại các bước kiểm uid 10001 ở `TEST_LOG.md`.
- Chưa có hạn mức dung lượng theo người dùng: đo `du -sh /data/users` sau vài tuần vận hành rồi quyết.
- SMTP chưa cấu hình mặc định: nhập ở Cài đặt › Hệ thống (hoặc env `SMTP_*`) rồi bấm "Gửi thư thử". Tới lúc đó tài khoản mới dùng
  ngay không cần xác nhận email, quên mật khẩu / đổi email không dùng được.
- **Link tải xuống khi lỗi** (401 hết phiên / 404 / 410 tệp mất) hiện trang JSON thô vì là link trực tiếp — cần trang lỗi thân
  thiện (việc UX tiếp theo).
- **Font Liberation rộng hơn Times**: lõi thu nhỏ chữ cho vừa khung (đo ở thí nghiệm: 532/1629 ký tự từ 9,96pt xuống 8,7–9,25pt
  với Sans). `Tự động` chọn `Có chân` cho bản gốc Times để giảm bớt; người dùng đổi bằng "Dựng lại với font khác".
- **Đổi email không cần phiên**: ai cầm link trong hộp thư mới là đổi được — chấp nhận vì bước xin link đòi mật khẩu, email cũ
  nhận thư báo, và link đặt lại mật khẩu đang chờ bị huỷ khi xác nhận.
- **Xoá tài khoản là xoá cứng** (DB + `/data/users/<id>`), không có thùng rác; tệp đang dịch chặn việc xoá.
- Câu chữ mới (Cài đặt › Tài khoản, menu avatar, font, dựng lại, 3 mẫu thư, 2 lỗi font) là **bản nháp — chờ BA duyệt** sau khi
  test (xem `KNOWN_ISSUES.md`).
