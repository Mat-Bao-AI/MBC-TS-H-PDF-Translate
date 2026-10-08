# PDF Translate SaaS — lớp web + tài khoản bọc quanh nhân dịch VI-Translate (AGPL-3.0; tác giả gốc breslee1707).
# Upstream KHÔNG nằm trong repo; kéo lúc build theo SHA đã ghim.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

# Repo của chính dự án là fork của upstream: nhánh `main` giữ nguyên mã upstream (chứa commit ghim bên dưới),
# mã dự án ở nhánh `pdf-translate-saas`. Không xoá / viết lại `main` — commit ghim phải còn tới được.
ARG UPSTREAM_REPO=https://github.com/Mat-Bao-AI/MBC-TS-H-PDF-Translate.git
ARG UPSTREAM_REF=ae156cf2792131009e6919f109e752141e2b2e11

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UPSTREAM_ROOT=/app/upstream \
    NOTO_FONT_PATH=/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf \
    DATA_DIR=/data \
    STATIC_DIR=/app/static

# curl: nhiều PaaS (vd Coolify) chạy health check BÊN TRONG container bằng curl — thiếu là bị đánh dấu unhealthy.
# fonts-liberation: phông dự phòng cùng hệ đo với Times, chữ Việt có dấu không bị chẻ hai kiểu.
# libgl1 + libglib2.0-0 cho opencv bản full (babeldoc đòi), libgomp1 cho onnxruntime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl libgl1 libglib2.0-0 libgomp1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# git clone --branch không nhận SHA, nên init + fetch đúng commit.
RUN git init -q /app/upstream \
    && git -C /app/upstream fetch -q --depth 1 "${UPSTREAM_REPO}" "${UPSTREAM_REF}" \
    && git -C /app/upstream checkout -q FETCH_HEAD \
    && rm -rf /app/upstream/.git /app/upstream/android

RUN pip install -r /app/upstream/requirements.txt
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

# Chạy bằng user thường uid/gid 10001, không phải root (Trivy DS002; Gate 2). Tạo user và đặt HOME TRƯỚC bước nướng
# tài sản: babeldoc ghi cứng CACHE_FOLDER = Path.home()/".cache"/"babeldoc" (phông/model/tiktoken) và còn ghi vào đó
# lúc chạy, upstream ghi bộ nhớ đệm bản dịch vào ~/.cache/pdf2zh → cache phải nằm trong HOME của app, app ghi được
# (nằm ở /root thì worker tải lại — hỏng khi không có mạng — hoặc lỗi ghi). HOME cũng phải ghi cứng bằng ENV vì
# setpriv (entrypoint hạ quyền khi container bị bật bằng user 0) không đặt lại HOME.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /home/app/.cache
ENV HOME=/home/app

# Nướng model bố cục (~75MB) + phông vào image: container đầu tiên không phải tải qua mạng. Cache babeldoc (~87 MB) ghi
# thẳng vào /home/app/.cache nhờ HOME ở trên; chown trong CÙNG RUN — tách ra thì chown chép lại cả cache thành lớp mới.
RUN python /app/upstream/scripts/fetch_assets.py \
    && cp /app/upstream/app/assets/doclayout.onnx /app/doclayout.onnx \
    && cp /app/upstream/app/assets/GoNotoKurrent-Regular.ttf /app/GoNotoKurrent-Regular.ttf \
    && ln -s /app/doclayout.onnx /home/app/.cache/doclayout.onnx \
    && chown -R app:app /home/app
# Lần đầu mỗi container, upstream (pdf2zh/doclayout.py) ghi đồ thị đã tối ưu ra "<PDF_TRANSLATE_MODEL>.optimized" NGAY
# CẠNH đường dẫn model — /app không cho app ghi ("SystemError : 13", mọi job dịch hỏng) → trỏ qua symlink trong HOME;
# tệp thật vẫn là /app/doclayout.onnx (root, chỉ đọc). Không nướng sẵn .optimized lúc build: onnxruntime báo đồ thị đó
# có thể gắn với phần cứng của máy tạo ra nó. Không bước build nào đọc biến này.
ENV PDF_TRANSLATE_MODEL=/home/app/.cache/doclayout.onnx

COPY backend/ /app/backend/
COPY --from=web /web/dist /app/static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# /data thuộc app TRƯỚC dòng VOLUME: volume có tên còn trống được Docker chép cả quyền sở hữu này sang, nên
# volume mới chạy được ngay (builder cũ còn BỎ mọi thay đổi trên /data sau dòng VOLUME). Thư mục host thuộc
# root / volume do image cũ (chạy root) ghi: xem docker-entrypoint.sh.
# chmod bằng RUN thay cho COPY --chmod: --chmod cần BuildKit, `docker build` không có buildx là builder cũ.
# Gỡ bit setuid/setgid khỏi mọi tệp của image (su, passwd, mount…): tiến trình app không còn đường nào leo lại root.
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + \
    && mkdir -p /data && chown app:app /data
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -sf http://127.0.0.1:8000/health || exit 1

WORKDIR /app/backend
# Container CHỈ được phép với tới qua reverse proxy (Traefik, Caddy, nginx…) — không publish cổng ra
# Internet. --proxy-headers: IP thật của người dùng (cho giới hạn đăng nhập sai / đăng ký) lấy từ
# X-Forwarded-For, nhưng uvicorn chỉ tin header đó từ các IP trong FORWARDED_ALLOW_IPS (uvicorn tự
# đọc biến này). "*" chỉ an toàn khi proxy ghi đè X-Forwarded-For của client — ops thu hẹp về IP/dải
# mạng của proxy bằng env, không cần build lại (xem docs/DEPLOY.md, bước kiểm X-Forwarded-For).
# --no-access-log: access log ghi cả query string → lộ token xác thực / đặt lại mật khẩu trong log.
ENV FORWARDED_ALLOW_IPS="*"
# Entrypoint kiểm $HOME/.cache và /data ghi được trước khi chạy app (bật bằng user 0 thì trao quyền /data cho app
# rồi hạ quyền); chỉ hỗ trợ uid 10001 hoặc user 0. USER dạng số (= user app): Kubernetes runAsNonRoot chỉ kiểm
# được uid số, tên user thì nó từ chối chạy.
USER 10001:10001
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-access-log"]
