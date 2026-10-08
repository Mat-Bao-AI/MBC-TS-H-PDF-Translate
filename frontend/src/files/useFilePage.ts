import { useCallback, useEffect, useRef, useState } from 'react';
import { toApiError, type ApiError } from '../api/client';
import { cacheGet, cacheSet } from '../lib/swrCache';
import { filesApi, isPending, type FilePage, type SortDir, type SortKey } from '../api/files';

export type FilePageState = { data: FilePage | null; error: ApiError | null; loading: boolean; reload: () => void };

/** Khoá bộ nhớ đệm danh sách tệp (tiền tố `files:` — xoá cả nhóm khi một tệp bị xoá). */
export const filePageKey = (q: string, page: number, sort: SortKey, dir: SortDir) => `files:${q}|${page}|${sort}|${dir}`;

export function useFilePage(q: string, page: number, sort: SortKey = 'created', dir: SortDir = 'desc'): FilePageState {
  const [data, setData] = useState<FilePage | null>(() => cacheGet<FilePage>(filePageKey(q, page, sort, dir)) ?? null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  // Số vé của yêu cầu mới nhất: phản hồi đến muộn của truy vấn cũ không được đè kết quả mới.
  const latest = useRef(0);

  const fetchPage = useCallback((visible: boolean) => {
    const ticket = ++latest.current;
    const key = filePageKey(q, page, sort, dir);
    // Đã xem trang này rồi: hiện ngay bản cũ, bản mới thay vào khi về (không có khung trống).
    const cached = cacheGet<FilePage>(key);
    if (cached) setData(cached);
    if (visible) setLoading(true);
    filesApi
      .list(q, page, sort, dir)
      .then((result) => {
        cacheSet(key, result);
        if (ticket !== latest.current) return;
        setData(result);
        setError(null);
      })
      .catch((caught) => {
        if (ticket === latest.current && visible) setError(toApiError(caught));
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false);
      });
  }, [q, page, sort, dir]);

  useEffect(() => {
    fetchPage(true);
  }, [fetchPage, version]);

  const pending = data?.items.some(isPending) ?? false;
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => fetchPage(false), 3000);
    return () => window.clearInterval(timer);
  }, [pending, fetchPage]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return { data, error, loading, reload };
}
