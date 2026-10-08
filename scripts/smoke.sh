#!/usr/bin/env bash
# Dịch thật một PDF qua API: (đăng ký → link xác thực từ log nếu máy chủ có gửi thư) → đăng nhập → tải lên → chờ → tải về.
# Dùng: BASE=http://localhost:18081 LOGS='docker compose -p pdf-translate logs app --no-log-prefix' scripts/smoke.sh <tệp.pdf>
# SMOKE_EMAIL + SMOKE_PASSWORD: dùng tài khoản đã xác nhận có sẵn (vd quản trị viên tạo ở /setup), bỏ bước đăng ký — BẮT
#   BUỘC khi máy chủ gửi thư thật (SMTP trong Cài đặt › Hệ thống / SMTP_HOST: link xác nhận đi qua email tới
#   smoke-<giờ>@example.com, không vào log) hoặc khi đăng ký đang đóng. Không đặt: tạo smoke-<giờ>@example.com; chưa cấu
#   hình gửi thư (mail_enabled=false) thì tài khoản dùng ngay (spec 2026-10-05 §5); MAIL_DEV_LOG=1 thì link đọc từ LOGS
#   (LOGS chỉ có link ở chế độ này). DB trống (cả khi đặt SMOKE_EMAIL): báo mở /setup trước.
# SMOKE_TIMEOUT=<giây, mặc định 900> — hạn chờ vòng lặp polling bản dịch trước khi bỏ cuộc.
set -euo pipefail
BASE="${BASE:-http://localhost:18081}"
LOGS="${LOGS:-docker compose -p pdf-translate logs app --no-log-prefix}"
PDF="${1:?Truyền đường dẫn tệp PDF}"
OUT="${OUT:-.build/smoke-out.pdf}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-900}"
FETCH=(-H 'X-Requested-With: fetch')
JSON=(-H 'Content-Type: application/json')
# Thân {"email","password"} dựng bằng python từ env và đi qua stdin: mật khẩu không nằm trên argv (`ps` đọc được argv).
credentials() { EMAIL="$EMAIL" PASSWORD="$PASSWORD" python3 -c \
  'import json, os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}))'; }
field() { python3 -c "import json, sys; print(json.load(sys.stdin)[\"$1\"])"; }

NEEDS_SETUP="Máy chủ chưa cài đặt (chưa có tài khoản nào): mở $BASE/setup tạo quản trị viên trước"
INSTANCE=$(curl -sf "$BASE/api/setup/status") || { echo "Không đọc được $BASE/api/setup/status" >&2; exit 1; }
# Trước cả hai nhánh: DB trống thì SMOKE_EMAIL cũng chưa tồn tại (đăng nhập sẽ trả 409 setup_required).
[ "$(printf '%s' "$INSTANCE" | field needs_setup)" = "False" ] || { echo "$NEEDS_SETUP" >&2; exit 1; }
if [ -n "${SMOKE_EMAIL:-}" ]; then
  EMAIL="$SMOKE_EMAIL"
  PASSWORD="${SMOKE_PASSWORD:?Đặt SMOKE_PASSWORD cùng SMOKE_EMAIL}"
else
  EMAIL="smoke-$(date +%s)@example.com"
  PASSWORD="mat-khau-smoke"
  credentials | curl -sf "${FETCH[@]}" "${JSON[@]}" --data-binary @- "$BASE/api/auth/register" >/dev/null \
    || { echo "Đăng ký thất bại (đăng ký đang đóng? → đặt SMOKE_EMAIL/SMOKE_PASSWORD)" >&2; exit 1; }
  if [ "$(printf '%s' "$INSTANCE" | field mail_enabled)" = "True" ]; then
    sleep 1
    # `|| true`: dưới set -e/pipefail, grep không khớp (chưa thấy mail trong log) làm cả pipeline thoát khác 0 và giết
    # script NGAY TẠI PHÉP GÁN, trước khi dòng kiểm tra bên dưới kịp in thông điệp chẩn đoán.
    TOKEN=$(bash -c "$LOGS" | grep -A4 "MAIL to=$EMAIL" | grep -o 'verify-email?token=[A-Za-z0-9_-]*' | tail -1 | cut -d= -f2 || true)
    [ -n "$TOKEN" ] || { echo "Không thấy link xác thực trong log (máy chủ gửi thư thật? → đặt SMOKE_EMAIL/SMOKE_PASSWORD của một tài khoản đã xác nhận; LOGS chỉ có link khi MAIL_DEV_LOG=1)" >&2; exit 1; }
    # curl không mang cookie verify_nonce của lượt đăng ký → server chỉ xác nhận email, không tự đăng nhập.
    curl -sf "${FETCH[@]}" "${JSON[@]}" -d "{\"token\":\"$TOKEN\"}" "$BASE/api/auth/verify-email" >/dev/null \
      || { echo "Xác nhận email thất bại" >&2; exit 1; }
  fi  # mail_enabled=false: tài khoản đã được xác nhận sẵn lúc đăng ký
fi
# Cookie phiên đặt Secure: đọc thẳng header (-i: header + thân) thay vì dựa vào cookie jar của curl. `|| true` cùng lý do
# như trên.
LOGIN=$(credentials | curl -s -i "${FETCH[@]}" "${JSON[@]}" --data-binary @- "$BASE/api/auth/login" | tr -d '\r' || true)
SESSION=$(printf '%s\n' "$LOGIN" | sed -n 's/^[Ss]et-[Cc]ookie: session=\([^;]*\).*/\1/p')
if [ -z "$SESSION" ]; then
  # Tài khoản duy nhất bị xoá giữa lúc đọc trạng thái và lúc đăng nhập → 409 setup_required.
  case "$LOGIN" in *'"setup_required"'*) echo "$NEEDS_SETUP" >&2; exit 1 ;; esac
  echo "Đăng nhập không trả cookie phiên" >&2; exit 1
fi
echo "SESSION=$SESSION"
COOKIE=(-H "Cookie: session=$SESSION")
ID=$(curl -sf "${FETCH[@]}" "${COOKIE[@]}" -F "file=@$PDF;type=application/pdf" -F language=vi "$BASE/api/files" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "FILE_ID=$ID"
echo "Tệp $ID — đang dịch…"
START=$(date +%s)
STATUS=""
until [[ "$STATUS" == done* || "$STATUS" == error* ]]; do
  if (( $(date +%s) - START >= SMOKE_TIMEOUT )); then
    echo "Hết thời gian chờ sau ${SMOKE_TIMEOUT}s. Trạng thái cuối: ${STATUS:-<chưa có>}" >&2
    exit 1
  fi
  sleep 5
  STATUS=$(curl -sf "${COOKIE[@]}" "$BASE/api/files/$ID" \
    | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["status"], s["done_pages"], s["total_pages"], s["message"][:100])' || true)
  echo "  $STATUS"
done
[[ "$STATUS" == done* ]] || { echo "Dịch lỗi: $STATUS" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"
curl -sf "${COOKIE[@]}" -o "$OUT" "$BASE/api/files/$ID/download"
[ "$(head -c 5 "$OUT")" = "%PDF-" ] || { echo "Tệp tải về không phải PDF" >&2; exit 1; }
echo "OK: dịch xong sau $(( $(date +%s) - START ))s, $(stat -c %s "$OUT") byte → $OUT"
