import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import type { FileItem } from '../api/files';
import { RequireAuth } from '../auth/RequireAuth';
import { AppShell } from '../components/AppShell';
import { HomePage } from '../pages/HomePage';
import { t } from '../i18n/t';
import { fileItem, filePage } from './fixtures';
import type { Reply } from './mockApi';
import { renderApp } from './render';

// Mỗi dòng bảng dựng năm IconButton có tooltip: một test HomePage đo 8–20 s khi máy dùng chung tải nặng (load ~19), vượt mốc
// 20 s của `--testTimeout=20000` ở vài test mỗi lượt chạy (trước cả khi có ↻ ở mọi dòng). Mọi test dùng trang chủ nạp tệp này.
vi.setConfig({ testTimeout: 60000 });

export const list = (items: FileItem[], total = items.length): Reply => ({ body: filePage(items, total) });
export const param = (url: string, name: string) => new URL(url, 'http://x').searchParams.get(name);

export function renderHome(at = '/') {
  return renderApp(
    <Routes>
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/" element={<HomePage />} />
        <Route path="/files/:id" element={<p>trang tệp</p>} />
      </Route>
      <Route path="/login" element={<p>trang đăng nhập</p>} />
    </Routes>,
    { at },
  );
}

/** `count` tệp xong, id `f00000000001`… và tên `tep-1.pdf`… */
export const seeded = (count: number, from = 1) => Array.from({ length: count }, (_, index) => {
  const n = from + index;
  return fileItem({ id: `f${String(n).padStart(11, '0')}`, filename: `tep-${n}.pdf` });
});
export const fileId = (n: string) => `f${n.padStart(11, '0')}`;
export const filesCalls = (calls: { method: string; url: string }[]) => calls.filter((call) => call.url.startsWith('/api/files?'));
export const rowBox = (id: string) => {
  const name = seeded(1, Number(id.slice(1)))[0].filename;
  return screen.getByRole('checkbox', { name: t('table.selectRow', { name }) });
};
