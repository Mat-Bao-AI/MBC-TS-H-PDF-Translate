import { useCallback, useEffect, useRef, useState } from 'react';
import { toApiError, type ApiError } from '../api/client';
import { filesApi, isPending, type FileItem } from '../api/files';
import { cacheGet, cacheSet } from '../lib/swrCache';
import { fileCacheKey } from './versions';

/** GET /api/files/{id} cho một trang theo tệp: hiện ngay bản trong bộ nhớ đệm rồi làm mới ngầm, bỏ phản hồi của id cũ khi route đã đổi,
 *  hỏi lại mỗi 2 s khi tệp còn chờ/đang chạy. `setItem` ghi cả vào bộ nhớ đệm (kết quả của POST dịch lại / khôi phục). */
export function useFileItem(id: string) {
  const [item, setItemState] = useState<FileItem | null>(() => cacheGet<FileItem>(fileCacheKey(id)) ?? null);
  const [error, setError] = useState<ApiError | null>(null);
  const setItem = useCallback((next: FileItem | null) => {
    if (next) cacheSet(fileCacheKey(next.id), next);
    setItemState(next);
  }, []);
  // Giữ id mới nhất: khi route chuyển sang /files/:id khác mà component không unmount,
  // một response đang bay cho id cũ phải bị bỏ qua thay vì ghi đè state của id mới.
  const currentId = useRef(id);
  currentId.current = id;

  const load = useCallback(
    () =>
      filesApi
        .get(id)
        .then((next) => { if (currentId.current !== id) return; setItem(next); setError(null); })
        .catch((caught) => { if (currentId.current !== id) return; setError(toApiError(caught)); }),
    [id, setItem],
  );

  useEffect(() => {
    setItem(cacheGet<FileItem>(fileCacheKey(id)) ?? null);
    setError(null);
    void load();
  }, [load, id, setItem]);

  const pending = item ? isPending(item) : false;
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => { void load(); }, 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  return { item, setItem, error, setError, load, currentId };
}
