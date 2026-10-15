import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FileItem } from '../api/files';
import { resetMetaCache } from '../files/useMeta';
import { fileCacheKey } from '../files/versions';
import { t } from '../i18n/t';
import { formatRelative } from '../lib/relativeTime';
import { cacheGet } from '../lib/swrCache';
import { META, SIGNED_IN, fileItem, fileVersion, snapshot } from '../test/fixtures';
import { mockApi } from '../test/mockApi';
import { renderApp } from '../test/render';
import { FileDetailPage } from './FileDetailPage';
import { FileVersionsPage } from './FileVersionsPage';

const ONE = 'GET /api/files/f00000000001';
const RESTORE = 'POST /api/files/f00000000001/versions/v00000000001/restore';

/** setupTests đặt matchMedia luôn false (màn hẹp); test màn rộng ghi đè bằng stub trả true (afterEach gỡ). */
function stubMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches, media: '(min-width: 1024px)', onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })));
}

/** Bản 1 (Gemini, hồ sơ Tài liệu kỹ thuật, tiếng Anh, KHÔNG bảng, chỉ có giờ bị thay), Bản 2 (Google miễn phí, có bảng), bản hiện tại
 *  Bản 3 (Google miễn phí). font_used đặt rõ ở mọi bản (fixture fileItem/fileVersion khác nhau ở đó). */
function threeVersions(overrides: Partial<FileItem> = {}): FileItem {
  return fileItem({
    status: 'done', version_no: 3, language: 'vi', font_used: 'sans', translated_at: '2026-10-15T10:00:00Z',
    versions: [
      fileVersion({ id: 'v00000000002', version_no: 2, language: 'vi', font_used: 'sans', has_tables: true, translated_at: '2026-10-14T10:00:00Z' }),
      fileVersion({ id: 'v00000000001', version_no: 1, language: 'en', engine: 'gemini', model: 'gemini-3.5-flash-lite', font_used: 'sans',
        config: snapshot(), has_tables: false, translated_at: null, archived_at: '2026-10-13T08:00:00Z' }),
    ],
    ...overrides,
  });
}

function renderVersions(routes: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: threeVersions() }, ...routes });
  renderApp(
    <Routes>
      <Route path="/files/:id/versions" element={<FileVersionsPage />} />
      <Route path="/files/:id" element={<p>trang tệp</p>} />
    </Routes>,
    { at: '/files/f00000000001/versions' },
  );
  return api;
}

const label = (n: number) => new RegExp(`^${t('detail.version.label', { n })}`);
const timeline = () => within(screen.getByTestId('timeline'));
const mark = (n: number) => timeline().getByRole('button', { name: label(n) });
const left = () => within(screen.getByTestId('left-side'));
const right = () => within(screen.getByTestId('right-side'));
const heading = (side: ReturnType<typeof within>) => side.getByRole('heading', { level: 2 });
const prev = () => screen.getByRole('button', { name: t('versions.prev') });
const next = () => screen.getByRole('button', { name: t('versions.next') });
const restoreButton = () => screen.getByRole('button', { name: t('restore.action') });

beforeEach(() => resetMetaCache());

const QUEUED = { status: 'queued' as const, retranslating: true, rebuild_font: 'auto' as const,
  retranslate_to: { language: 'vi', engine: 'google_free', model: null, font: 'auto' } };

describe('FileVersionsPage', () => {
  it('puts every version on the timeline oldest first and shows the latest on the right with its predecessor on the left', async () => {
    renderVersions();
    const marks = await within(await screen.findByTestId('timeline')).findAllByRole('button');
    expect(marks.map((button) => button.textContent)).toEqual([
      expect.stringMatching(label(1)), expect.stringMatching(label(2)), expect.stringMatching(label(3)),
    ]);
    expect(mark(3)).toHaveAttribute('aria-pressed', 'true');
    expect(heading(right())).toHaveTextContent(label(3));
    expect(heading(right())).toHaveTextContent(t('detail.version.current'));
    expect(heading(left())).toHaveTextContent(label(2));
    expect(within(screen.getByTestId('config-compare')).queryAllByText(t('versions.differs'))).toHaveLength(0); // Bản 2 ≡ Bản 3
    expect(screen.queryByRole('button', { name: t('restore.action') })).toBeNull(); // bản hiện tại: không khôi phục
    const nav = screen.getByRole('navigation', { name: 'breadcrumbs' });
    expect(within(nav).getByRole('link', { name: 'Báo cáo.pdf' })).toHaveAttribute('href', '/files/f00000000001');
    expect(within(nav).getByText(t('versions.crumb'))).toBeInTheDocument();
  });

  it('steps back and forward with Trước / Sau, says "Không có bản trước" at the oldest and highlights the rows that differ', async () => {
    renderVersions();
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(prev());
    expect(heading(right())).toHaveTextContent(label(2));
    expect(heading(left())).toHaveTextContent(label(1));
    const table = within(screen.getByTestId('config-compare'));
    expect(table.getByText(t('detail.config.language')).closest('[data-differs="true"]')).not.toBeNull(); // Tiếng Anh ≠ Tiếng Việt
    expect(table.getByText(t('detail.config.profile')).closest('[data-differs="true"]')).not.toBeNull(); // Tài liệu kỹ thuật ≠ Cơ bản
    expect(table.getByText(t('detail.config.font')).closest('[data-differs="true"]')).toBeNull(); // cùng font
    await user.click(prev());
    expect(heading(right())).toHaveTextContent(label(1));
    expect(screen.getByTestId('left-empty')).toHaveTextContent(t('versions.noPrevious'));
    expect(prev()).toBeDisabled();
    await user.click(next());
    await user.click(next());
    expect(mark(3)).toHaveAttribute('aria-pressed', 'true');
    expect(next()).toBeDisabled();
  });

  it('lets the user compare any two versions once the toggle is on, never the same one on both sides', async () => {
    renderVersions();
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(screen.getByRole('checkbox', { name: t('versions.anyPair') }));
    expect(screen.getByLabelText(t('versions.right'))).toHaveValue('2'); // chỉ số của Bản 3
    expect(within(screen.getByLabelText(t('versions.right'))).queryByRole('option', { name: label(2) })).toBeNull(); // đang là trái
    await user.selectOptions(screen.getByLabelText(t('versions.left')), '0');
    expect(heading(left())).toHaveTextContent(label(1));
    expect(heading(right())).toHaveTextContent(label(3));
    expect(within(screen.getByLabelText(t('versions.right'))).queryByRole('option', { name: label(1) })).toBeNull();
    expect(mark(1)).toBeDisabled(); // mốc đang là trái không chọn làm phải được
    expect(mark(1)).toHaveTextContent(t('versions.left'));
  });

  it('shows both PDFs side by side on a wide screen, the old one from its version URL', async () => {
    stubMatchMedia(true);
    renderVersions();
    await screen.findByTestId('timeline');
    const leftFrame = screen.getByTitle(t('versions.frameTitle', { name: 'Báo cáo.pdf', n: 2 })) as HTMLIFrameElement;
    const rightFrame = screen.getByTitle(t('versions.frameTitle', { name: 'Báo cáo.pdf', n: 3 })) as HTMLIFrameElement;
    expect(leftFrame.src).toContain('/api/files/f00000000001/versions/v00000000002/download?inline=1');
    expect(rightFrame.src).toContain('/api/files/f00000000001/download?kind=translated&inline=1');
    expect(getComputedStyle(screen.getByTestId('sides')).flexDirection).toBe('row');
  });

  it('stacks the two sides on a narrow screen', async () => {
    renderVersions();
    await screen.findByTestId('timeline');
    expect(getComputedStyle(screen.getByTestId('sides')).flexDirection).toBe('column');
  });

  it('greys out a version whose file is gone, says so instead of a frame and locks restore', async () => {
    renderVersions({ [ONE]: { body: threeVersions({ versions: [
      fileVersion({ id: 'v00000000002', version_no: 2, font_used: 'sans', translated_at: '2026-10-14T10:00:00Z' }),
      fileVersion({ id: 'v00000000001', version_no: 1, font_used: 'sans', available: false }),
    ] }) } });
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    expect(mark(1)).toHaveTextContent(t('detail.version.missing'));
    expect(mark(1)).toHaveAttribute('data-muted', 'true'); // mốc của bản mất tệp bị làm mờ, không chỉ có nhãn
    expect(mark(2)).not.toHaveAttribute('data-muted');
    await user.click(mark(1));
    expect(right().getByText(t('detail.version.missing'))).toBeInTheDocument();
    expect(right().queryByTitle(t('versions.frameTitle', { name: 'Báo cáo.pdf', n: 1 }))).toBeNull();
    expect(restoreButton()).toBeDisabled();
  });

  it('locks restore and explains while the file is queued or running', async () => {
    renderVersions({ [ONE]: { body: threeVersions({ status: 'queued', retranslating: true, rebuild_font: 'auto',
      retranslate_to: { language: 'vi', engine: 'google_free', model: null, font: 'auto' } }) } });
    const user = userEvent.setup();
    expect(await screen.findByText(t('versions.pendingNotice'))).toBeInTheDocument();
    await user.click(mark(2));
    expect(restoreButton()).toBeDisabled();
  });

  it('restores the chosen version after a confirmation, warns when its segment table is missing, and returns to the file page', async () => {
    const restored = threeVersions({ status: 'queued', restoring: true, restore_version: 'v00000000001', retranslating: true });
    const { calls } = renderVersions({ [RESTORE]: { status: 202, body: restored } });
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(mark(2));
    await user.click(restoreButton());
    let dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('restore.body', { k: 2, n: 3, next: 4 }))).toBeInTheDocument();
    expect(dialog.getByText(t('restore.pruneNote'))).toBeInTheDocument();
    expect(dialog.queryByText(t('restore.noTables'))).toBeNull(); // Bản 2 có bảng
    await user.click(dialog.getByRole('button', { name: t('common.cancel') }));
    await user.click(mark(1)); // Gemini, không bảng
    await user.click(restoreButton());
    dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('restore.noTables'))).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: t('restore.confirm') }));
    expect(await screen.findByText('trang tệp')).toBeInTheDocument();
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/files/f00000000001/versions/v00000000001/restore')).toBe(true);
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/files\/f00000000001$/);
    expect(cacheGet<FileItem>(fileCacheKey('f00000000001'))).toEqual(restored); // trang chi tiết hiện ngay "Đang khôi phục…"
  });

  it('keeps the version list when caching the restore answer, so the file page names the source version at once', async () => {
    // 202 của khôi phục là to_item: KHÔNG có `versions` (chỉ GET /api/files/{id} có) — JSON bỏ khoá undefined.
    const accepted = { ...threeVersions({ status: 'queued', restoring: true, restore_version: 'v00000000001', retranslating: true }), versions: undefined };
    const { fetchMock } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: threeVersions() }, [RESTORE]: { status: 202, body: accepted } });
    renderApp(
      <Routes>
        <Route path="/files/:id/versions" element={<FileVersionsPage />} />
        <Route path="/files/:id" element={<FileDetailPage />} />
      </Routes>,
      { at: '/files/f00000000001/versions' },
    );
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(mark(1));
    await user.click(restoreButton());
    // Trang chi tiết tự làm mới bị giữ lại: thứ nó hiện chỉ có thể đến từ phản hồi khôi phục đã ghi vào bộ nhớ đệm.
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) =>
      input === '/api/files/f00000000001' && (init?.method ?? 'GET') === 'GET' ? new Promise<Response>(() => undefined) : original(input, init));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('restore.confirm') }));
    expect(await screen.findByText(t('restore.running', { k: 1 }))).toBeInTheDocument();
    expect(screen.queryByText(t('restore.runningUnknown'))).toBeNull();
    expect(screen.getByRole('link', { name: t('detail.versionsButton', { n: 2 }) })).toBeInTheDocument();
    expect(cacheGet<FileItem>(fileCacheKey('f00000000001'))?.versions).toHaveLength(2);
  });

  it('shows the not-found placeholder when the file disappears while the page is open', async () => {
    // Phản hồi do test điều khiển: tệp đang chờ (trang hỏi lại mỗi 2 s), rồi bị xoá ở nơi khác.
    let served: { status?: number; body: unknown } = { body: threeVersions(QUEUED) };
    renderVersions({ [ONE]: () => served });
    await screen.findByTestId('timeline');
    served = { status: 404, body: { detail: { code: 'not_found' } } };
    expect(await screen.findByText(t('detail.notFound'), undefined, { timeout: 6000 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('common.backHome') })).toHaveAttribute('href', '/');
    expect(screen.queryByTestId('timeline')).toBeNull();
  });

  it('shows the server reason when a restore is refused and stays on the page', async () => {
    renderVersions({ [RESTORE]: { status: 409, body: { detail: { code: 'not_restorable' } } } });
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(mark(1));
    await user.click(restoreButton());
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('restore.confirm') }));
    expect(await screen.findByText(t('error.not_restorable'))).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/\/versions$/);
    expect(restoreButton()).toBeEnabled();
  });

  it('uses the translation time on the marks and falls back to the archive time for versions from before this release', async () => {
    renderVersions();
    await screen.findByTestId('timeline');
    const archiveNote = t('versions.archivedAt', { time: '' }).trim();
    expect(mark(1)).toHaveTextContent(t('versions.archivedAt', { time: formatRelative('2026-10-13T08:00:00Z') }));
    expect(mark(2)).toHaveTextContent(formatRelative('2026-10-14T10:00:00Z'));
    expect(mark(2)).not.toHaveTextContent(archiveNote);
    expect(mark(3)).not.toHaveTextContent(archiveNote);
  });

  it('explains a missing file', async () => {
    renderVersions({ [ONE]: { status: 404, body: { detail: { code: 'not_found' } } } });
    expect(await screen.findByText(t('detail.notFound'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('common.backHome') })).toHaveAttribute('href', '/');
  });

  it('keeps focus on the Select the user changed, on both sides', async () => {
    renderVersions();
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(screen.getByRole('checkbox', { name: t('versions.anyPair') }));
    await user.selectOptions(screen.getByLabelText(t('versions.left')), '0');
    expect(screen.getByLabelText(t('versions.left'))).toHaveFocus();
    await user.selectOptions(screen.getByLabelText(t('versions.right')), '1');
    expect(screen.getByLabelText(t('versions.right'))).toHaveFocus();
    expect(heading(right())).toHaveTextContent(label(2));
  });

  it('names the step buttons without the glyphs and flags the left mark programmatically', async () => {
    renderVersions();
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    expect(prev()).toHaveAccessibleName(t('versions.prev'));
    expect(next()).toHaveAccessibleName(t('versions.next'));
    expect(mark(2)).toHaveAttribute('aria-current', 'true');
    expect(mark(1)).not.toHaveAttribute('aria-current');
    await user.click(prev());
    expect(mark(1)).toHaveAttribute('aria-current', 'true');
  });

  it('keeps the muted state and a badge on a selected mark whose file is gone', async () => {
    renderVersions({ [ONE]: { body: threeVersions({ versions: [
      fileVersion({ id: 'v00000000002', version_no: 2, font_used: 'sans', translated_at: '2026-10-14T10:00:00Z' }),
      fileVersion({ id: 'v00000000001', version_no: 1, font_used: 'sans', available: false }),
    ] }) } });
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(mark(1));
    expect(mark(1)).toHaveAttribute('aria-pressed', 'true');
    expect(mark(1)).toHaveAttribute('data-muted', 'true');
    expect(mark(1)).toHaveTextContent(t('detail.version.missing'));
  });

  it('keeps a pinned side on the same version when the list grows, and falls back to the latest when it shrinks past it', async () => {
    const v = (n: number, extra: Partial<Parameters<typeof fileVersion>[0]> = {}) =>
      fileVersion({ id: `v0000000000${n}`, version_no: n, font_used: 'sans', translated_at: `2026-10-1${n}T10:00:00Z`, ...extra });
    // Phản hồi do test điều khiển: poll 2 s luôn nhận bản "hiện hành" cho tới khi test đổi — không đua với đồng hồ.
    let served = threeVersions({ ...QUEUED, versions: [v(2), v(1)] });
    renderVersions({ [ONE]: () => ({ body: served }) });
    const user = userEvent.setup();
    await screen.findByTestId('timeline');
    await user.click(screen.getByRole('checkbox', { name: t('versions.anyPair') }));
    await user.selectOptions(screen.getByLabelText(t('versions.left')), '0'); // trái ghim Bản 1
    await user.click(mark(2)); // phải ghim Bản 2
    expect(heading(left())).toHaveTextContent(label(1));
    served = threeVersions({ ...QUEUED, version_no: 4, versions: [v(3), v(2), v(1)] }); // dài hơn
    await timeline().findByRole('button', { name: label(4) }, { timeout: 6000 });
    expect(heading(right())).toHaveTextContent(label(2));
    expect(heading(left())).toHaveTextContent(label(1));
    served = threeVersions({ status: 'done', version_no: 4, versions: [v(3)] }); // ngắn hơn: Bản 1, 2 bị tỉa
    await waitFor(() => expect(timeline().queryByRole('button', { name: label(1) })).toBeNull(), { timeout: 6000 });
    expect(heading(right())).toHaveTextContent(label(4)); // Bản 2 biến mất → bản mới nhất
    expect(heading(left())).toHaveTextContent(label(3)); // Bản 1 biến mất → mặc định đi theo phải
  });
});
