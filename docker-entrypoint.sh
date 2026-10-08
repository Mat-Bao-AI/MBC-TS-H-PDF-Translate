#!/bin/sh
# Điểm vào của image. App chạy bằng user thường `app` (uid/gid 10001); dữ liệu ở $DATA_DIR (mặc định /data).
# Chỉ hỗ trợ hai cách bật:
# - uid 10001 (mặc định): kiểm $HOME/.cache, $DATA_DIR và các tệp dữ liệu đang có đều ghi được — không thì dừng ngay
#   và nói rõ cách sửa, thay vì /health vẫn 200 mà mọi lượt dịch / lượt ghi DB hỏng lưng chừng.
# - user 0 (`docker run --user 0`, `user: "0"` trong compose — người vận hành chủ động chọn): lối thoát cho volume do
#   image cũ (chạy root) ghi hoặc thư mục host thuộc root. Trao quyền $DATA_DIR cho app, hạ quyền hẳn về app (không
#   capability, no_new_privs) rồi chạy lại CHÍNH script này để qua đúng các bước kiểm của uid 10001.
# uid khác (vd --user 12345) không vào được /home/app (0700) → mọi lượt dịch hỏng → dừng ngay, kèm thông báo.
set -eu

APP_USER=app
APP_UID=10001
DATA_DIR="${DATA_DIR:-/data}"

uid=$(id -u)
gid=$(id -g)

# Cách sửa khi thiếu quyền ghi — in kèm mọi thông báo lỗi quyền.
print_supported() {
    if [ "$uid" != "$APP_UID" ]; then
        cat >&2 <<EOF
Container đang chạy bằng uid=$uid (đặt bằng --user / user: trong compose). Image này chỉ hỗ trợ uid $APP_UID (user
'$APP_USER', mặc định) hoặc user 0 (sửa quyền thư mục dữ liệu một lần rồi tự hạ về uid $APP_UID): bỏ --user / user:
rồi bật lại; nếu khi đó vẫn báo lỗi quyền, làm theo hướng dẫn in ra cho uid $APP_UID.
EOF
    fi
}

fail_home() {
    cat >&2 <<EOF
LỖI: tiến trình app (uid=$uid gid=$gid) không ghi được vào $1 — bộ nhớ đệm của nhân dịch (phông, model, bản
dịch) nằm ở đó: web vẫn lên nhưng mọi lượt dịch sẽ hỏng. HOME phải là /home/app (mặc định của image, đừng đổi).
EOF
    print_supported
    exit 1
}

fail_data() {
    echo "LỖI: tiến trình app (uid=$uid gid=$gid) không ghi được vào $1 (thư mục dữ liệu: $DATA_DIR)." >&2
    if [ "$uid" = "$APP_UID" ]; then
        cat >&2 <<EOF
Image này chạy bằng user thường '$APP_USER' (uid/gid $APP_UID), không chạy bằng root. Thư mục dữ liệu (hoặc tệp trong
đó) đang thuộc user khác — thường là thư mục host thuộc root, hoặc volume do image cũ (chạy bằng root) đã ghi.
Sửa MỘT lần, chọn một trong hai cách:
  1. Trên host: chown -R $APP_UID:$APP_UID <thư mục trên host gắn vào $DATA_DIR>
  2. Dừng container cũ đang dùng thư mục này (nếu còn chạy), rồi bật một lần bằng user 0 (docker run --user 0 ...,
     hoặc user: "0" trong compose): entrypoint trao quyền $DATA_DIR cho uid $APP_UID rồi hạ quyền — app vẫn chạy
     bằng uid $APP_UID. Sau đó bỏ user 0.
EOF
    fi
    print_supported
    exit 1
}

if [ "$uid" = 0 ]; then
    if [ ! -d "$DATA_DIR" ]; then
        echo "LỖI: DATA_DIR=$DATA_DIR không phải thư mục — không có gì để trao quyền." >&2
        exit 1
    fi
    data_real=$(cd "$DATA_DIR" && pwd -P)
    # Không bao giờ chown -R vào thư mục hệ thống (DATA_DIR đặt nhầm, hoặc symlink trỏ vào đó).
    case "$data_real" in
        / | /app | /app/* | /bin | /bin/* | /boot | /boot/* | /dev | /dev/* | /etc | /etc/* | /home | /home/* | /lib*)
            refuse=1 ;;
        /proc | /proc/* | /root | /root/* | /run | /run/* | /sbin | /sbin/* | /sys | /sys/* | /usr | /usr/* | /var | /var/*)
            refuse=1 ;;
        *)
            refuse=0 ;;
    esac
    if [ "$refuse" = 1 ]; then
        echo "LỖI: DATA_DIR=$DATA_DIR (thực chất là $data_real) nằm trong thư mục hệ thống — từ chối trao quyền cho app." >&2
        echo "Gắn thư mục dữ liệu vào /data (mặc định) hoặc đặt DATA_DIR ra ngoài các thư mục hệ thống." >&2
        exit 1
    fi
    # Chỉ đụng tới thứ chưa thuộc app (lần sau gần như không tốn gì) và không vượt sang hệ tệp khác (-xdev).
    # -execdir + chown -h: chown chạy từ chính thư mục chứa mục đó và đổi chủ của chính symlink — không đi theo symlink
    # (kể cả symlink cài vào giữa đường dẫn) ra ngoài $DATA_DIR. Chỉ thư mục, symlink và tệp thường MỘT liên kết: tệp có
    # liên kết cứng có thể chính là một tệp ngoài $DATA_DIR, tệp đặc biệt (thiết bị…) không phải dữ liệu của app.
    # Tệp biến mất giữa chừng / chown lỗi không được làm hỏng lần khởi động: cảnh báo, rồi bước kiểm phía dưới quyết.
    find "$data_real" -xdev ! -user "$APP_USER" \( -type d -o -type l -o \( -type f -links 1 \) \) \
        -execdir chown -h "$APP_USER:$APP_USER" {} + \
        || echo "Cảnh báo: chưa trao quyền được hết $data_real cho $APP_USER (tệp biến mất giữa chừng / chown lỗi) — xem các dòng trên." >&2
    skipped=$(find "$data_real" -xdev ! -user "$APP_USER" ! -type d ! -type l ! \( -type f -links 1 \) -print 2>/dev/null | wc -l)
    if [ "$skipped" -gt 0 ]; then
        echo "Cảnh báo: bỏ qua $skipped mục trong $data_real chưa thuộc $APP_USER vì là tệp có liên kết cứng hoặc tệp đặc biệt —" \
            "không tự chown; kiểm bằng: find $data_real -xdev ! -user $APP_USER ! -type d ! -type l" >&2
    fi
    # Đường dẫn tuyệt đối (nơi Dockerfile chép script), không "$0": gọi kiểu `sh ./docker-entrypoint.sh` thì "$0" là
    # đường dẫn tương đối, có thể không trỏ tới đâu / không thực thi được khi chạy lại.
    exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups --inh-caps=-all --bounding-set=-all --no-new-privs \
        /usr/local/bin/docker-entrypoint.sh "$@"
fi

home_cache="${HOME:-}/.cache"
if [ ! -d "$home_cache" ] || [ ! -w "$home_cache" ]; then
    fail_home "$home_cache"
fi

if [ ! -d "$DATA_DIR" ] || [ ! -w "$DATA_DIR" ]; then
    fail_data "$DATA_DIR"
fi
# Thư mục gốc ghi được chưa đủ: DB và thư mục tệp người dùng còn lại từ image cũ có thể vẫn thuộc root.
for path in "$DATA_DIR"/app.db* "$DATA_DIR/users"; do
    if [ -e "$path" ] && [ ! -w "$path" ]; then
        fail_data "$path"
    fi
done

exec "$@"
