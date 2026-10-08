// Bộ nhớ đệm "cũ-mà-dùng-được" (stale-while-revalidate): trang trả về từ lần xem trước hiện NGAY, rồi tự làm mới ngầm,
// nên chuyển menu không còn khung trống → thẻ bật ra làm bố cục nhảy. Chỉ giữ trong bộ nhớ trang (mất khi tải lại).
const store = new Map<string, unknown>();

export function cacheGet<T>(key: string): T | undefined {
  return store.get(key) as T | undefined;
}

export function cacheSet<T>(key: string, value: T): void {
  store.set(key, value);
}

/** Xoá các khoá bắt đầu bằng `prefix`; không truyền = xoá hết (đăng nhập/đăng xuất: dữ liệu của người khác không được lộ). */
export function cacheClear(prefix = ''): void {
  for (const key of [...store.keys()]) {
    if (key.startsWith(prefix)) store.delete(key);
  }
}
