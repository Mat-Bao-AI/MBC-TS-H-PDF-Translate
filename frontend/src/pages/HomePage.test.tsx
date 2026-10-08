import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SETTINGS, SIGNED_IN, fileItem, signedInAs } from '../test/fixtures';
import { mockApi, sequence } from '../test/mockApi';

import { list, param, renderHome } from '../test/home';

beforeEach(() => resetMetaCache());

describe('HomePage', () => {
  it('greets the user and invites a first upload', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS }, 'GET /api/files': list([]) });
    renderHome();
    expect(await screen.findByRole('heading', { name: t('home.greeting', { name: 'an' }) })).toBeInTheDocument();
    expect(await screen.findByText(t('home.empty.title'))).toBeInTheDocument();
    await userEvent.setup().click(screen.getAllByRole('button', { name: t('home.upload') })[0]);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('lists files with their status and actions', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([
        fileItem({ id: 'f00000000001', filename: 'Xong.pdf', status: 'done' }),
        fileItem({ id: 'f00000000002', filename: 'Dang-dich.pdf', status: 'running', done_pages: 1, total_pages: 2 }),
        fileItem({ id: 'f00000000003', filename: 'Loi.pdf', status: 'error' }),
      ]),
    });
    renderHome();
    expect(await screen.findByRole('link', { name: 'Xong.pdf' })).toHaveAttribute('href', '/files/f00000000001');
    expect(screen.getByText(t('status.runningPct', { pct: 50 }))).toBeInTheDocument();
    expect(screen.getByText(t('status.error'))).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: t('action.downloadTranslated') })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: t('action.retranslate') })).toHaveLength(3);
  });

  it('filters by name through the URL and clears the filter', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': ({ url }) => (param(url, 'q') ? list([]) : list([fileItem()])),
    });
    renderHome();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('home.filter')), 'báo');
    expect(await screen.findByText(t('home.noMatch', { q: 'báo' }))).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/?q=b%C3%A1o');
    expect(calls.some((call) => call.url.includes('q=b%C3%A1o'))).toBe(true);
    await user.click(screen.getByRole('button', { name: t('home.clearFilter') }));
    expect(await screen.findByRole('link', { name: 'Báo cáo.pdf' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  });

  it('moves between pages and keeps the page in the URL', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': ({ url }) => list([fileItem({ filename: `trang-${param(url, 'page')}.pdf` })], 45),
    });
    renderHome();
    await screen.findByRole('link', { name: 'trang-1.pdf' });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Page 2' }));
    expect(await screen.findByRole('link', { name: 'trang-2.pdf' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/?page=2');
  });

  it('falls back to the last page when the URL points past the end', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': ({ url }) => {
        const page = Number(param(url, 'page'));
        return page > 2 ? list([], 25) : list([fileItem({ filename: `trang-${page}.pdf` })], 25);
      },
    });
    renderHome('/?page=9');
    expect(await screen.findByRole('link', { name: 'trang-2.pdf' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/?page=2');
    expect(screen.queryByText(t('home.empty.title'))).not.toBeInTheDocument();
  });

  it('offers a retry when the list fails to load', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': sequence({ status: 500, body: {} }, list([fileItem()])),
    });
    renderHome();
    expect(await screen.findByText(t('home.loadError'))).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: t('common.retry') }));
    expect(await screen.findByRole('link', { name: 'Báo cáo.pdf' })).toBeInTheDocument();
  });

  it('navigates to the file detail page from the "Xem" button of a done row', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({ id: 'f00000000001', filename: 'Xong.pdf', status: 'done' })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Xong.pdf' });
    await userEvent.setup().click(screen.getByRole('button', { name: t('action.view') }));
    expect(await screen.findByText('trang tệp')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/files/f00000000001');
  });

  it.each(['queued', 'running'] as const)('keeps "Xem" and "Tải bản dịch" for a %s rebuild (the old translation stays)', async (status) => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({
        id: 'f00000000004', filename: 'Dung-lai.pdf', status, rebuilding: true, rebuild_font: 'serif', font_used: 'sans',
      })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Dung-lai.pdf' });
    expect(screen.getByRole('button', { name: t('action.view') })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('action.downloadTranslated') }))
      .toHaveAttribute('href', '/api/files/f00000000004/download?kind=translated');
    expect(screen.getByRole('button', { name: t('action.retranslate') })).toHaveAttribute('aria-disabled', 'true');
  });

  it('deletes a file after confirmation', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': sequence(list([fileItem()]), list([])),
      'DELETE /api/files/f00000000001': { status: 204 },
    });
    renderHome();
    const user = userEvent.setup();
    await screen.findByRole('link', { name: 'Báo cáo.pdf' });
    await user.click(screen.getByRole('button', { name: t('action.delete') }));
    expect(await screen.findByText(t('delete.body', { name: 'Báo cáo.pdf' }))).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: t('delete.confirm') }));
    expect(await screen.findByText(t('home.empty.title'))).toBeInTheDocument();
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true);
  });

  it('shows the engine next to the language for files translated with a key', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([
        fileItem({ id: 'f00000000001', filename: 'AI.pdf', engine: 'gemini', model: 'gemini-3.5-flash-lite' }),
        fileItem({ id: 'f00000000002', filename: 'Thuan.pdf' }),
      ]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'AI.pdf' });
    expect(screen.getByText(`${t('file.translatedTo', { language: 'Tiếng Việt' })} · Gemini 3.5 Flash-Lite`)).toBeInTheDocument();
    expect(screen.getByText(t('file.translatedTo', { language: 'Tiếng Việt' }))).toBeInTheDocument();
  });

  it('greets by display name when the user has one', async () => {
    mockApi({ ...signedInAs({ display_name: 'Cường' }), 'GET /api/meta': { body: META }, 'GET /api/files': list([]) });
    renderHome();
    expect(await screen.findByRole('heading', { name: t('home.greeting', { name: 'Cường' }) })).toBeInTheDocument();
  });
});

describe('HomePage — font', () => {
  it('adds the font actually used to the file caption', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({ id: 'f00000000001', filename: 'Co-chan.pdf', font_used: 'serif' })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Co-chan.pdf' });
    expect(screen.getByText(`${t('file.translatedTo', { language: 'Tiếng Việt' })} · ${t('font.used.serif')}`)).toBeInTheDocument();
  });
});

describe('AppShell', () => {
  it('has no search box in the top bar', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list([fileItem()]) });
    renderHome('/files/abc');
    await screen.findByRole('button', { name: t('shell.accountMenu') });
    expect(screen.queryByRole('search')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('Tìm tệp…')).not.toBeInTheDocument();
  });

  it('links to the source code only when configured', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: { ...META, source_url: 'https://git.example.com/pdf' } },
      'GET /api/files': list([]),
    });
    renderHome();
    expect(await screen.findByRole('link', { name: t('shell.source') }))
      .toHaveAttribute('href', 'https://git.example.com/pdf');
  });
});
