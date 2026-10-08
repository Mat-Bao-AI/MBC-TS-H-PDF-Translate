import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SIGNED_IN, fileItem } from '../test/fixtures';
import { fileId, list, renderHome, rowBox, seeded } from '../test/home';
import { mockApi, sequence } from '../test/mockApi';

// Tách file riêng: mỗi file test có jsdom riêng. Emotion chỉ thêm (không gỡ) stylesheet nên trong một file dài
// getComputedStyle / getByRole chậm dần theo số test, các test cuối vượt thời hạn khi máy tải nặng.
beforeEach(() => resetMetaCache());

const bar = () => within(screen.getByRole('group', { name: t('home.selectionBar') }));

describe('HomePage — selection and bulk delete', () => {
  const one = fileId;

  it('selects the rows of the page from the header checkbox and clears them', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(3)) });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    expect(screen.queryByText(t('home.selected', { n: 3 }))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: t('table.selectAll') }));
    expect(bar().getByText(t('home.selected', { n: 3 }))).toBeInTheDocument();
    expect(rowBox(one('2'))).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: t('home.clearSelection') }));
    expect(screen.queryByText(t('home.selected', { n: 3 }))).not.toBeInTheDocument();
    expect(rowBox(one('2'))).not.toBeChecked();
  });

  it('offers "select all N" only when the page is fully selected and more files exist', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(2), 25) });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    expect(bar().getByText(t('home.selected', { n: 1 }))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('home.selectAllMatching', { total: 25 }) })).not.toBeInTheDocument();
    fireEvent.click(rowBox(one('2')));
    fireEvent.click(screen.getByRole('button', { name: t('home.selectAllMatching', { total: 25 }) }));
    expect(bar().getByText(t('home.selectedAll', { total: 25 }))).toBeInTheDocument();
    // bỏ một dòng thì rời chế độ "tất cả"
    fireEvent.click(rowBox(one('1')));
    expect(bar().getByText(t('home.selected', { n: 1 }))).toBeInTheDocument();
  });

  it('announces the selection through a persistent status region', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(2)) });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    const live = screen.getAllByRole('status').find((node) => node.textContent === '')!;
    expect(live).toBeDefined();
    fireEvent.click(rowBox(one('1')));
    expect(live).toHaveTextContent(t('home.selected', { n: 1 }));
    fireEvent.click(screen.getByRole('button', { name: t('home.clearSelection') }));
    expect(live).toBeEmptyDOMElement();
  });

  it('gives the checkboxes and sort buttons Vietnamese names that contain the visible text', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(2)) });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    expect(screen.getByRole('checkbox', { name: t('table.selectAll') })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: t('table.selectRow', { name: 'tep-2.pdf' }) })).toBeInTheDocument();
    for (const column of ['home.col.name', 'home.col.created', 'home.col.status'] as const) {
      expect(screen.getByRole('button', { name: t('table.sortBy', { column: t(column) }) })).toHaveTextContent(t(column));
    }
    expect(document.querySelectorAll('[aria-label^="Select "], [aria-label^="sort by "]')).toHaveLength(0);
  });

  it('does not offer "select all N" when everything fits on the page', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(2)) });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(screen.getByRole('checkbox', { name: t('table.selectAll') }));
    expect(screen.queryByRole('button', { name: /Chọn tất cả/ })).not.toBeInTheDocument();
  });

  it('bulk-deletes the selected ids after confirmation, reports the result and reloads', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': sequence(list(seeded(3)), list(seeded(1, 3))),
      'POST /api/files/bulk-delete': { body: { deleted: 2, skipped_running: 0 } },
    });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(rowBox(one('2')));
    fireEvent.click(within(screen.getByRole('group', { name: t('home.selectionBar') })).getByRole('button', { name: t('action.delete') }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('bulk.title', { n: 2 }))).toBeInTheDocument();
    expect(within(dialog).getByText(t('bulk.body'))).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: t('delete.confirm') }));
    expect(await screen.findByText(t('bulk.done', { deleted: 2 }))).toBeInTheDocument();
    expect(screen.getByText(t('bulk.done', { deleted: 2 })).closest('[role="status"]')).not.toBeNull();
    const post = calls.find((call) => call.method === 'POST')!;
    expect(JSON.parse(String(post.body))).toEqual({ ids: [one('1'), one('2')] });
    expect(post.headers.get('X-Requested-With')).toBe('fetch');
    await waitFor(() => expect(screen.queryByRole('link', { name: 'tep-1.pdf' })).not.toBeInTheDocument());
    expect(screen.queryByText(t('home.selected', { n: 2 }))).not.toBeInTheDocument();
  });

  it('bulk-deletes every match of the filter in "all" mode and mentions skipped running files', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': sequence(list(seeded(2), 25), list([])),
      'POST /api/files/bulk-delete': { body: { deleted: 24, skipped_running: 1 } },
    });
    renderHome('/?q=tep');
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(screen.getByRole('checkbox', { name: t('table.selectAll') }));
    fireEvent.click(screen.getByRole('button', { name: t('home.selectAllMatching', { total: 25 }) }));
    fireEvent.click(within(screen.getByRole('group', { name: t('home.selectionBar') })).getByRole('button', { name: t('action.delete') }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('bulk.title', { n: 25 }))).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: t('delete.confirm') }));
    expect(await screen.findByText(`${t('bulk.done', { deleted: 24 })}${t('bulk.skipped', { skipped: 1 })}`)).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((call) => call.method === 'POST')!.body))).toEqual({ all: true, q: 'tep' });
  });

  it('shows an error and keeps the selection when the bulk delete fails', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list(seeded(2)),
      'POST /api/files/bulk-delete': { status: 500, body: { detail: { code: 'unknown' } } },
    });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(within(screen.getByRole('group', { name: t('home.selectionBar') })).getByRole('button', { name: t('action.delete') }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('delete.confirm') }));
    expect(await screen.findByText(t('error.unknown'))).toBeInTheDocument();
    expect(bar().getByText(t('home.selected', { n: 1 }))).toBeInTheDocument();
  });

  it('clears the selection when the page, the filter or the sort changes', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(2), 45) });
    renderHome();
    const user = userEvent.setup();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
    await waitFor(() => expect(screen.queryByText(t('home.selected', { n: 1 }))).not.toBeInTheDocument());
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(screen.getByRole('button', { name: t('table.sortBy', { column: t('home.col.status') }) }));
    await waitFor(() => expect(screen.queryByText(t('home.selected', { n: 1 }))).not.toBeInTheDocument());
    fireEvent.click(rowBox(one('1')));
    await user.type(screen.getByLabelText(t('home.filter')), 'x');
    await waitFor(() => expect(screen.queryByText(t('home.selected', { n: 1 }))).not.toBeInTheDocument());
  });

  it('keeps the selection (by id) across the 3 s refresh and drops ids that vanished', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': sequence(
        list([...seeded(1), fileItem({ id: one('2'), filename: 'tep-2.pdf', status: 'running' })]),
        list([fileItem({ id: one('2'), filename: 'tep-2.pdf', status: 'running', done_pages: 1 })]),
      ),
    });
    renderHome();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    fireEvent.click(rowBox(one('1')));
    fireEvent.click(rowBox(one('2')));
    expect(bar().getByText(t('home.selected', { n: 2 }))).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('link', { name: 'tep-1.pdf' })).not.toBeInTheDocument(), { timeout: 8000 });
    expect(bar().getByText(t('home.selected', { n: 1 }))).toBeInTheDocument();
    expect(rowBox(one('2'))).toBeChecked();
  }, 15000);
});

