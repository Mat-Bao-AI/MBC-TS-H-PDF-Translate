import { act, cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FileItem } from '../api/files';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SETTINGS, SIGNED_IN, fileItem, fileVersion, snapshot } from '../test/fixtures';
import { holdRequests, mockApi, sequence } from '../test/mockApi';
import { renderApp } from '../test/render';
import { FileDetailPage } from './FileDetailPage';

const ONE = 'GET /api/files/f00000000001';

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function GoToB() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate('/files/bbbbbbbbbbbb')}>
      go
    </button>
  );
}

function renderDetail() {
  return renderApp(
    <Routes>
      <Route path="/files/:id" element={<FileDetailPage />} />
      <Route path="/" element={<p>trang chính</p>} />
    </Routes>,
    { at: '/files/f00000000001' },
  );
}

beforeEach(() => resetMetaCache());

describe('FileDetailPage loading', () => {
  it('shows a skeleton card, not a spinner, under the breadcrumb while loading', async () => {
    const { fetchMock } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done' }) } });
    const hold = holdRequests(fetchMock, '/api/files/');
    renderDetail();
    expect(await screen.findByTestId('breadcrumb-band')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: t('common.loading') })).toBeInTheDocument();
    await act(async () => hold.release());
    expect(await screen.findByRole('heading', { level: 1, name: 'Báo cáo.pdf' })).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: t('common.loading') })).not.toBeInTheDocument();
  });

  it('renders the cached file at once on a revisit, then refreshes it', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done', filename: 'cu.pdf' }) } });
    renderDetail();
    expect(await screen.findByRole('heading', { level: 1, name: 'cu.pdf' })).toBeInTheDocument();
    cleanup();

    const { fetchMock } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done', filename: 'moi.pdf' }) } });
    const hold = holdRequests(fetchMock, '/api/files/');
    renderDetail();
    expect(await screen.findByRole('heading', { level: 1, name: 'cu.pdf' })).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: t('common.loading') })).not.toBeInTheDocument();
    await act(async () => hold.release());
    expect(await screen.findByRole('heading', { level: 1, name: 'moi.pdf' })).toBeInTheDocument();
  });
});

describe('FileDetailPage', () => {
  it('links to the versions page when there are old versions, shows the current configuration and says what it was restored from', async () => {
    const versions = [fileVersion({ id: 'v00000000001', version_no: 1 }), fileVersion({ id: 'v00000000002', version_no: 2 })];
    const item = fileItem({ status: 'done', version_no: 3, restored_from: 1, engine: 'gemini', model: 'gemini-3.8-flash', font_used: 'sans',
      config: snapshot(), versions });
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: item } });
    renderDetail();
    const link = await screen.findByRole('link', { name: t('detail.versionsButton', { n: 2 }) });
    expect(link).toHaveAttribute('href', '/files/f00000000001/versions');
    expect(screen.getByText(new RegExp(t('detail.restoredFrom', { k: 1 })))).toBeInTheDocument(); // dòng mô tả
    expect(screen.queryByTestId('versions-panel')).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: t('detail.currentConfig') }));
    const config = within(await screen.findByTestId('current-config'));
    expect(config.getByText('Tài liệu kỹ thuật')).toBeInTheDocument();
    expect(config.getByText(t('profiles.value.terms.keep'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('action.downloadTranslated') })).toHaveAttribute('href', '/api/files/f00000000001/download?kind=translated');
  });

  it('shows the restoring banner without a progress bar while a version is being restored, keeping the current translation usable', async () => {
    const item = fileItem({
      status: 'running', version_no: 3, done_pages: 0, total_pages: 0, rebuild_font: 'serif', retranslating: true, restoring: true,
      restore_version: 'v00000000001', retranslate_to: { language: 'en', engine: 'gemini', model: 'gemini-3.8-flash', font: 'serif' },
      versions: [fileVersion({ id: 'v00000000001', version_no: 1 }), fileVersion({ id: 'v00000000002', version_no: 2 })],
    });
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: item } });
    renderDetail();
    expect(await screen.findByText(t('restore.running', { k: 1 }))).toBeInTheDocument();
    expect(screen.queryByText(t('retranslate.running', { target: `Tiếng Anh · Gemini 3.8 Flash · ${t('font.serif')}` }))).not.toBeInTheDocument();
    expect(screen.queryByText(t('detail.starting'))).not.toBeInTheDocument(); // không thanh tiến độ / dòng bước
    expect(screen.getByRole('link', { name: t('action.downloadTranslated') })).toHaveAttribute('href', '/api/files/f00000000001/download?kind=translated');
    expect(screen.getByRole('tab', { name: t('viewer.translated') })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('detail.versionsButton', { n: 2 }) })).toBeInTheDocument();
  });

  it('never shows a placeholder in the restoring banner when the source version is no longer listed', async () => {
    const item = fileItem({ status: 'queued', version_no: 3, retranslating: true, restoring: true, restore_version: 'v0000000gone', versions: [] });
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: item } });
    renderDetail();
    expect(await screen.findByText(t('restore.runningUnknown'))).toBeInTheDocument();
    expect(screen.queryByText(/\?/)).not.toBeInTheDocument();
  });

  it('has no versions link or version number for a file that was never retranslated', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done', versions: [] }) } });
    renderDetail();
    await screen.findByRole('heading', { level: 1, name: 'Báo cáo.pdf' });
    const toVersions = [...screen.queryAllByRole('link'), ...screen.queryAllByRole('button')]
      .filter((element) => element.getAttribute('href') === '/files/f00000000001/versions');
    expect(toVersions).toHaveLength(0);
    expect(screen.queryByText(new RegExp(t('file.version', { n: 1 })))).not.toBeInTheDocument();
  });

  it('shows a breadcrumb back to the list and the file name as the page title', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done' }) } });
    renderDetail();
    const nav = await screen.findByRole('navigation', { name: 'breadcrumbs' });
    expect(within(nav).getByRole('link', { name: t('home.myFiles') })).toHaveAttribute('href', '/');
    expect(within(nav).getByText('Báo cáo.pdf')).toHaveAttribute('aria-current', 'location');
    expect(screen.getByRole('heading', { level: 1, name: 'Báo cáo.pdf' })).toBeInTheDocument();
    expect(screen.getByText(t('status.done'))).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: t('common.backHome') })).not.toBeInTheDocument();
    await userEvent.setup().click(within(nav).getByRole('link', { name: t('home.myFiles') }));
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  });

  it('has a back button in the breadcrumb band that goes home client-side', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done' }) } });
    renderDetail();
    const band = await screen.findByTestId('breadcrumb-band');
    await act(() => Promise.resolve()); // IconButton tip floating: lượt đầu InlineTip rồi gắn lại nút (xem ghi chú cũ)
    const back = within(band).getByRole('link', { name: t('detail.back') });
    expect(back).toHaveAttribute('href', '/');
    expect(within(band).getByRole('navigation', { name: 'breadcrumbs' })).toBeInTheDocument();
    await userEvent.setup().click(back);
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  });

  it('puts the full file name in the title attribute of the heading', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done' }) } });
    renderDetail();
    expect(await screen.findByRole('heading', { level: 1, name: 'Báo cáo.pdf' })).toHaveAttribute('title', 'Báo cáo.pdf');
  });

  it('deletes the file after confirmation and returns to the list', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'done' }) },
      'DELETE /api/files/f00000000001': { status: 204 },
    });
    renderDetail();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('action.delete') }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('delete.body', { name: 'Báo cáo.pdf' }))).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: t('delete.confirm') }));
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/files/f00000000001')).toBe(true);
  });

  it('follows progress until the translation is ready', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      [ONE]: sequence(
        { body: fileItem({ status: 'running', done_pages: 1, total_pages: 2 }) },
        { body: fileItem({ status: 'done' }) },
      ),
    });
    renderDetail();
    expect(await screen.findByText(t('detail.progress', { done: 1, total: 2 }))).toBeInTheDocument();
    expect(await screen.findByText(t('file.translatedTo', { language: 'Tiếng Việt' }))).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(await screen.findByRole('link', { name: t('action.downloadTranslated') }))
      .toHaveAttribute('href', '/api/files/f00000000001/download?kind=translated');
    expect(screen.getByRole('link', { name: t('action.downloadOriginal') }))
      .toHaveAttribute('href', '/api/files/f00000000001/download?kind=original');
  });

  it('warns about passages left untranslated', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ untranslated: 4 }) } });
    renderDetail();
    expect(await screen.findByText(t('detail.untranslated', { count: 4 }))).toBeInTheDocument();
  });

  it('shows the PDF viewer only once the translation is done', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'running', done_pages: 1, total_pages: 2 }) },
    });
    renderDetail();
    expect(await screen.findByText(t('detail.progress', { done: 1, total: 2 }))).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: t('viewer.translated') })).not.toBeInTheDocument();
  });

  it('renders the PDF viewer with tabs once the file is done', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { body: fileItem({ status: 'done' }) } });
    renderDetail();
    expect(await screen.findByRole('tab', { name: t('viewer.translated') })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: t('viewer.original') })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('viewer.openNewTab') }))
      .toHaveAttribute('href', '/api/files/f00000000001/download?kind=translated&inline=1');
  });

  it('retranslates a failed file in place from the Dịch lại dialog', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/settings': { body: SETTINGS },
      [ONE]: { body: fileItem({ status: 'error', message: 'Tệp này là bản scan thành ảnh' }) },
      'POST /api/files/f00000000001/retranslate': { status: 202, body: fileItem({ status: 'queued', message: '' }) },
    });
    renderDetail();
    expect(await screen.findByText(/Tệp này là bản scan thành ảnh/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: t('action.retranslate') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.warnError'))).toBeInTheDocument();
    await dialog.findByLabelText('Google miễn phí');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(await screen.findByText(t('detail.waiting'))).toBeInTheDocument();
    const post = calls.find((call) => call.method === 'POST')!;
    expect(post.url).toBe('/api/files/f00000000001/retranslate');
    expect(JSON.parse(String(post.body))).toEqual({ language: 'vi', engine: 'google_free', model: null, font: 'auto' });
  });

  it('clears the reason of a refused retranslate once a new one is queued', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/settings': { body: SETTINGS },
      [ONE]: { body: fileItem({ status: 'error', message: 'Tệp này là bản scan thành ảnh' }) },
      'POST /api/files/f00000000001/retranslate': sequence(
        { status: 429, body: { detail: { code: 'too_many_pending', limit: 2 } } },
        { status: 202, body: fileItem({ status: 'queued', message: '' }) },
      ),
    });
    renderDetail();
    const user = userEvent.setup();
    const send = async () => {
      await user.click(await screen.findByRole('button', { name: t('action.retranslate') }));
      const dialog = within(await screen.findByRole('dialog'));
      await dialog.findByLabelText('Google miễn phí');
      await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    };
    await send();
    expect(await screen.findByText(t('error.too_many_pending', { limit: 2 }))).toBeInTheDocument();
    await send();
    expect(await screen.findByText(t('detail.waiting'))).toBeInTheDocument(); // trước vòng hỏi tiến độ 2 s đầu tiên
    expect(screen.queryByText(t('error.too_many_pending', { limit: 2 }))).not.toBeInTheDocument();
  });

  it('explains a missing file', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, [ONE]: { status: 404, body: { detail: { code: 'not_found' } } } });
    renderDetail();
    expect(await screen.findByText(t('detail.notFound'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('common.backHome') })).toHaveAttribute('href', '/');
  });

  it('ignores a stale response for a file id that is no longer current', async () => {
    let resolveOld!: (item: FileItem) => void;
    const oldRequest = new Promise<FileItem>((resolve) => { resolveOld = resolve; });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url === '/api/auth/me') return jsonResponse(200, { id: 'u1', email: 'an@example.com' });
        if (url === '/api/meta') return jsonResponse(200, META);
        if (url === '/api/files/aaaaaaaaaaaa') return jsonResponse(200, await oldRequest);
        if (url === '/api/files/bbbbbbbbbbbb') {
          return jsonResponse(200, fileItem({ id: 'bbbbbbbbbbbb', filename: 'moi.pdf', status: 'done' }));
        }
        return jsonResponse(500, { detail: { code: 'unmocked', url } });
      }),
    );

    renderApp(
      <Routes>
        <Route
          path="/files/:id"
          element={
            <>
              <FileDetailPage />
              <GoToB />
            </>
          }
        />
      </Routes>,
      { at: '/files/aaaaaaaaaaaa' },
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: 'go' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'moi.pdf' })).toBeInTheDocument();

    await act(async () => {
      resolveOld(fileItem({ id: 'aaaaaaaaaaaa', filename: 'cu.pdf', status: 'done' }));
      await oldRequest;
    });

    expect(screen.getByRole('heading', { level: 1, name: 'moi.pdf' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: 'cu.pdf' })).not.toBeInTheDocument();
  });

  it('keeps Dịch lại usable on a new file after navigating away mid-request', async () => {
    let resolveA!: (item: FileItem) => void;
    const requestA = new Promise<FileItem>((resolve) => { resolveA = resolve; });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const url = typeof input === 'string' ? input : input.toString();
        const method = (init.method ?? 'GET').toUpperCase();
        if (url === '/api/auth/me') return jsonResponse(200, { id: 'u1', email: 'an@example.com' });
        if (url === '/api/meta') return jsonResponse(200, META);
        if (url === '/api/settings') return jsonResponse(200, SETTINGS);
        if (method === 'GET' && url === '/api/files/aaaaaaaaaaaa') {
          return jsonResponse(200, fileItem({ id: 'aaaaaaaaaaaa', status: 'error', message: 'lỗi A' }));
        }
        if (method === 'GET' && url === '/api/files/bbbbbbbbbbbb') {
          return jsonResponse(200, fileItem({ id: 'bbbbbbbbbbbb', status: 'error', message: 'lỗi B' }));
        }
        if (method === 'POST' && url === '/api/files/aaaaaaaaaaaa/retranslate') return jsonResponse(202, await requestA);
        return jsonResponse(500, { detail: { code: 'unmocked', url } });
      }),
    );

    renderApp(
      <Routes>
        <Route path="/files/:id" element={<><FileDetailPage /><GoToB /></>} />
      </Routes>,
      { at: '/files/aaaaaaaaaaaa' },
    );

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('action.retranslate') }));
    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByLabelText('Google miễn phí');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(screen.getByRole('button', { name: t('action.retranslate') })).toBeDisabled(); // POST của A còn đang bay
    await user.click(screen.getByRole('button', { name: 'go' }));
    expect(await screen.findByText(/lỗi B/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('action.retranslate') })).toBeEnabled(); // đổi tệp: trạng thái gửi đặt lại

    await act(async () => {
      resolveA(fileItem({ id: 'aaaaaaaaaaaa', status: 'queued', message: '' }));
      await requestA;
    });

    expect(screen.getByRole('button', { name: t('action.retranslate') })).toBeEnabled();
    expect(screen.getByText(/lỗi B/)).toBeInTheDocument(); // phản hồi muộn của A không đè tệp B
  });

  it('adds the font actually used to the caption', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', font_used: 'sans' }) },
    });
    renderDetail();
    expect(await screen.findByText(
      `${t('file.translatedTo', { language: 'Tiếng Việt' })} · Gemini 3.5 Flash-Lite · ${t('font.used.sans')}`,
    )).toBeInTheDocument();
  });

  it('rebuilds with another font from a dialog that preselects the other profile', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'done', font: 'auto', font_used: 'sans' }) },
      'POST /api/files/f00000000001/rebuild': {
        status: 202, body: fileItem({ status: 'queued', font: 'auto', font_used: 'sans', rebuilding: true, rebuild_font: 'serif' }),
      },
    });
    renderDetail();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('rebuild.action') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByLabelText(t('font.field'))).toHaveValue('serif');
    await user.click(dialog.getByRole('button', { name: t('rebuild.confirm') }));
    expect(await screen.findByText(t('rebuild.running', { font: t('font.serif') }))).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const post = calls.find((call) => call.method === 'POST' && call.url.endsWith('/rebuild'))!;
    expect(JSON.parse(String(post.body))).toEqual({ font: 'serif' });
    expect(screen.queryByRole('button', { name: t('rebuild.action') })).not.toBeInTheDocument();
  });

  it('closes the rebuild dialog and shows the error on the page when the rebuild is refused', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'done', font_used: 'sans' }) },
      'POST /api/files/f00000000001/rebuild': { status: 409, body: { detail: { code: 'not_rebuildable' } } },
    });
    renderDetail();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('rebuild.action') }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('rebuild.confirm') }));
    expect(await screen.findByText(t('error.not_rebuildable'))).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not render two viewers if the API reports done and rebuilding together', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'done', rebuilding: true, rebuild_font: 'sans' }) },
    });
    renderDetail();
    await screen.findByText(t('rebuild.running', { font: t('font.sans') }));
    expect(screen.getAllByRole('tablist')).toHaveLength(1);
  });

  it('keeps the old translation viewable and downloadable while rebuilding', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'running', rebuilding: true, rebuild_font: 'sans', done_pages: 1, total_pages: 2 }) },
    });
    renderDetail();
    expect(await screen.findByText(t('rebuild.running', { font: t('font.sans') }))).toBeInTheDocument();
    expect(screen.getByText(t('detail.progress', { done: 1, total: 2 }))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('action.downloadTranslated') }))
      .toHaveAttribute('href', '/api/files/f00000000001/download?kind=translated');
    expect(screen.getByRole('tab', { name: t('viewer.translated') })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('rebuild.action') })).not.toBeInTheDocument();
    expect(screen.queryByText(t('detail.done'))).not.toBeInTheDocument();
  });

  it('says why the last rebuild failed and that the previous translation is kept', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'done', rebuild_error: 'Máy chủ thiếu tệp font của bản dịch. Báo quản trị viên.' }) },
    });
    renderDetail();
    expect(await screen.findByText(
      t('rebuild.failed', { reason: 'Máy chủ thiếu tệp font của bản dịch. Báo quản trị viên' }),
    )).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('rebuild.action') })).toBeInTheDocument();
  });

  it('shows the stage message while a handoff job runs', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({ status: 'running', engine: 'gemini', model: 'gemini-3.5-flash-lite', stage: 'translate', done_pages: 3, total_pages: 10 }) },
    });
    renderDetail();
    expect(await screen.findByText(`${t('detail.stage.translate', { engine: 'Gemini (Google AI Studio)' })} ${t('detail.stageProgress', { done: 3, total: 10 })}`)).toBeInTheDocument();
    expect(screen.getByText(`${t('file.translatedTo', { language: 'Tiếng Việt' })} · Gemini 3.5 Flash-Lite`)).toBeInTheDocument();
    expect(screen.queryByText(t('detail.progress', { done: 3, total: 10 }))).not.toBeInTheDocument();
  });

  it('retranslates a done file from a dialog prefilled with its choices and keeps the old translation meanwhile', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/settings': { body: SETTINGS },
      [ONE]: { body: fileItem({ status: 'done', language: 'en', font: 'serif' }) },
      'POST /api/files/f00000000001/retranslate': {
        status: 202,
        body: fileItem({
          status: 'queued', language: 'en', font: 'serif', rebuild_font: 'auto', retranslating: true,
          retranslate_to: { language: 'vi', engine: 'google_free', model: null, font: 'auto' },
        }),
      },
    });
    renderDetail();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('action.retranslate') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.warnDone'))).toBeInTheDocument();
    await waitFor(() => expect(dialog.getByLabelText(t('upload.language'))).toHaveValue('en'));
    await user.selectOptions(dialog.getByLabelText(t('upload.language')), 'vi');
    await user.selectOptions(await dialog.findByLabelText(t('font.field')), 'auto');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(await screen.findByText(t('retranslate.running', { target: `Tiếng Việt · Google miễn phí · ${t('font.auto')}` })))
      .toBeInTheDocument();
    expect(screen.getByText(t('detail.waiting'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('action.downloadTranslated') })).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((call) => call.method === 'POST')!.body)))
      .toEqual({ language: 'vi', engine: 'google_free', model: null, font: 'auto' });
  });

  it('says where a done file is being retranslated to while the old translation stays viewable and downloadable', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      [ONE]: { body: fileItem({
        status: 'running', done_pages: 1, total_pages: 2, rebuild_font: 'serif', retranslating: true,
        retranslate_to: { language: 'en', engine: 'gemini', model: 'gemini-3.8-flash', font: 'serif' },
      }) },
    });
    renderDetail();
    expect(await screen.findByText(t('retranslate.running', { target: `Tiếng Anh · Gemini 3.8 Flash · ${t('font.serif')}` })))
      .toBeInTheDocument();
    expect(screen.getByText(t('detail.progress', { done: 1, total: 2 }))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('action.downloadTranslated') }))
      .toHaveAttribute('href', '/api/files/f00000000001/download?kind=translated');
    expect(screen.getByRole('tab', { name: t('viewer.translated') })).toBeInTheDocument();
    expect(screen.getByText(t('file.translatedTo', { language: 'Tiếng Việt' }))).toBeInTheDocument(); // dòng mô tả: bản cũ
    expect(screen.queryByRole('button', { name: t('action.retranslate') })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('rebuild.action') })).not.toBeInTheDocument();
    expect(screen.queryByText(t('rebuild.running', { font: t('font.serif') }))).not.toBeInTheDocument();
  });
});
