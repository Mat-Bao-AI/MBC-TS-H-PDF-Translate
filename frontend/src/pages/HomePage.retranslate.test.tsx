import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SETTINGS, SIGNED_IN, fileItem } from '../test/fixtures';
import { fileId, list, renderHome, rowBox, seeded } from '../test/home';
import { mockApi, sequence, type Call } from '../test/mockApi';

// Tách file riêng như HomePage.selection / HomePage.actions: mỗi file test một jsdom, stylesheet của Emotion không dồn lên.
beforeEach(() => resetMetaCache());

const one = fileId;
const BASE = { ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } };
const bar = () => within(screen.getByRole('group', { name: t('home.selectionBar') }));
const rowOf = (name: string) =>
  (screen.getByRole('link', { name }).closest('tr') ?? screen.getByRole('link', { name }).closest('[role="row"]')) as HTMLElement;
const posted = (calls: Call[], url: string) =>
  calls.filter((call) => call.method === 'POST' && call.url === url).map((call) => JSON.parse(String(call.body)));

/** ↻ của một dòng — đợi InlineTip → FloatingTip gắn lại nút xong rồi mới truy vấn (bẫy Gamut, xem HomePage.actions). */
async function redoOf(name: string) {
  await act(async () => {});
  return within(rowOf(name)).getByRole('button', { name: t('action.retranslate') });
}

describe('HomePage — dịch lại', () => {
  it("retranslates one row from its ↻ with the file's own choices prefilled and reloads the list", async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /api/files': sequence(
        list([fileItem({ id: one('1'), filename: 'Xong.pdf', language: 'en', font: 'sans' })]),
        list([fileItem({
          id: one('1'), filename: 'Xong.pdf', language: 'en', font: 'sans', status: 'queued', rebuild_font: 'sans',
          retranslating: true, retranslate_to: { language: 'en', engine: 'google_free', model: null, font: 'sans' },
        })]),
      ),
      'POST /api/files/f00000000001/retranslate': { status: 202, body: fileItem({ id: one('1'), status: 'queued' }) },
    });
    renderHome();
    await screen.findByRole('link', { name: 'Xong.pdf' });
    const user = userEvent.setup();
    await user.click(await redoOf('Xong.pdf'));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.title', { name: 'Xong.pdf' }))).toBeInTheDocument();
    expect(await dialog.findByLabelText('Google miễn phí')).toBeChecked();
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    await waitFor(() => expect(posted(calls, '/api/files/f00000000001/retranslate')).toEqual([
      { language: 'en', engine: 'google_free', model: null, font: 'sans' },
    ]));
    expect(await screen.findByText(t('status.queued'))).toBeInTheDocument(); // danh sách nạp lại
  });

  it('shows on the page why a single retranslate was refused', async () => {
    mockApi({
      ...BASE,
      'GET /api/files': list([fileItem({ id: one('1'), filename: 'Xong.pdf' })]),
      'POST /api/files/f00000000001/retranslate': { status: 429, body: { detail: { code: 'too_many_pending', limit: 2 } } },
    });
    renderHome();
    await screen.findByRole('link', { name: 'Xong.pdf' });
    const user = userEvent.setup();
    await user.click(await redoOf('Xong.pdf'));
    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByLabelText('Google miễn phí');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(await screen.findByText(t('error.too_many_pending', { limit: 2 }))).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('reloads the list when a single retranslate is refused, so the row shows its real state', async () => {
    mockApi({
      ...BASE,
      'GET /api/files': sequence(
        list([fileItem({ id: one('1'), filename: 'Xong.pdf' })]),
        list([fileItem({ id: one('1'), filename: 'Xong.pdf', status: 'queued' })]), // ai đó (tab khác) vừa xếp nó
      ),
      'POST /api/files/f00000000001/retranslate': { status: 409, body: { detail: { code: 'not_retranslatable' } } },
    });
    renderHome();
    await screen.findByRole('link', { name: 'Xong.pdf' });
    const user = userEvent.setup();
    await user.click(await redoOf('Xong.pdf'));
    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByLabelText('Google miễn phí');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(await screen.findByText(t('error.not_retranslatable'))).toBeInTheDocument();
    expect(await screen.findByText(t('status.queued'))).toBeInTheDocument(); // danh sách nạp lại
    expect(screen.getByText(t('error.not_retranslatable'))).toBeInTheDocument(); // nạp lại không xoá lý do
  });

  it('retranslates the selected rows with their own settings, reports the queue and clears the selection', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /api/files': list(seeded(3)),
      'POST /api/files/bulk-retranslate': { body: { queued: 1, skipped_pending: 1, skipped_limit: 0, limit: 3 } },
    });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(rowBox(one('2')));
    fireEvent.click(bar().getByRole('button', { name: t('action.retranslate') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.bulkTitle', { n: 2 }))).toBeInTheDocument();
    fireEvent.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    const message = `${t('retranslate.queued', { queued: 1 })}${t('retranslate.skippedPending', { skipped: 1 })}`;
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByText(message).closest('[role="status"]')).not.toBeNull();
    expect(posted(calls, '/api/files/bulk-retranslate')).toEqual([{ ids: [one('1'), one('2')], settings: null }]);
    expect(screen.queryByRole('group', { name: t('home.selectionBar') })).not.toBeInTheDocument();
  });

  it('retranslates every match of the filter with one shared choice and says how many must wait for a slot', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /api/files': list(seeded(2), 25),
      'POST /api/files/bulk-retranslate': { body: { queued: 3, skipped_pending: 0, skipped_limit: 22, limit: 3 } },
    });
    renderHome('/?q=tep');
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(screen.getByRole('checkbox', { name: t('table.selectAll') }));
    fireEvent.click(screen.getByRole('button', { name: t('home.selectAllMatching', { total: 25 }) }));
    fireEvent.click(bar().getByRole('button', { name: t('action.retranslate') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.bulkTitle', { n: 25 }))).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(dialog.getByLabelText(t('retranslate.scope.apply')));
    await user.selectOptions(await dialog.findByLabelText(t('font.field')), 'serif');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(await screen.findByText(
      `${t('retranslate.queued', { queued: 3 })}${t('retranslate.skippedLimit', { skipped: 22, limit: 3 })}`,
    )).toBeInTheDocument();
    expect(posted(calls, '/api/files/bulk-retranslate')).toEqual([
      { all: true, q: 'tep', settings: { language: 'vi', engine: 'google_free', model: null, font: 'serif' } },
    ]);
  });

  it('shows why a shared choice was refused and keeps the selection', async () => {
    mockApi({
      ...BASE,
      'GET /api/files': list(seeded(2)),
      'POST /api/files/bulk-retranslate': { status: 400, body: { detail: { code: 'missing_api_key' } } },
    });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(bar().getByRole('button', { name: t('action.retranslate') }));
    const dialog = within(await screen.findByRole('dialog'));
    const user = userEvent.setup();
    await user.click(dialog.getByLabelText(t('retranslate.scope.apply')));
    await dialog.findByLabelText('Google miễn phí');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(await screen.findByText(t('error.missing_api_key'))).toBeInTheDocument();
    expect(bar().getByText(t('home.selected', { n: 1 }))).toBeInTheDocument();
  });
});
