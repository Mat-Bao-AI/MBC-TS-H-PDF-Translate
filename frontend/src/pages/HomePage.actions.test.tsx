import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SIGNED_IN, fileItem } from '../test/fixtures';
import { list, renderHome } from '../test/home';
import { mockApi } from '../test/mockApi';
import type { FileStatus } from '../api/files';

// Tách file riêng: mỗi file test có jsdom riêng. Emotion chỉ thêm (không gỡ) stylesheet nên trong một file dài
// getComputedStyle / getByRole chậm dần theo số test, các test cuối vượt thời hạn khi máy tải nặng.
beforeEach(() => resetMetaCache());

describe('HomePage — action icon slots', () => {
  const rowOf = (name: string) => screen.getByRole('link', { name }).closest('tr') ?? screen.getByRole('link', { name }).closest('[role="row"]')!;

  it.each([
    ['error', 'action.noTranslation.error'],
    ['queued', 'action.noTranslation.pending'],
    ['running', 'action.noTranslation.pending'],
  ] as const)('disables Xem and Tải bản dịch for a %s file, with an explanation, and they do nothing', async (status: FileStatus, key) => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({ id: 'f00000000009', filename: 'Khong-co.pdf', status })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Khong-co.pdf' });
    // Gamut's ToolTip starts as InlineTip and swaps to FloatingTip in a passive effect, which REMOUNTS the button. Under load
    // findBy can resolve between the commit and that effect, leaving us with a detached button (focus() on it does nothing).
    // Flush effects first, then query fresh.
    await act(async () => {});
    const row = within(rowOf('Khong-co.pdf') as HTMLElement);
    const fresh = (name: string) => row.getByRole('button', { name });
    const view = fresh(t('action.view'));
    const download = fresh(t('action.downloadTranslated'));
    for (const button of [view, download]) {
      expect(button).toHaveAttribute('aria-disabled', 'true');
      expect(button).not.toBeDisabled(); // vẫn nhận pointer/focus để tooltip hiện
      expect(button).not.toHaveAttribute('href');
    }
    expect(row.queryByRole('link', { name: t('action.downloadTranslated') })).not.toBeInTheDocument();
    expect(screen.getAllByText(t(key)).length).toBeGreaterThan(0); // text tooltip có trong DOM
    const writes = () => calls.filter((call) => call.method !== 'GET').length; // queued/running: the poll keeps GETting
    const user = userEvent.setup();
    await user.click(view);
    await user.click(download);
    expect(screen.queryByText('trang tệp')).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
    expect(writes()).toBe(0);
    expect(view.isConnected).toBe(true); // the swap must have settled before we grabbed it (see above)
    view.focus({ preventScroll: true });
    expect(view).toHaveFocus();
  });

  it('shows the tooltip with the reason when hovering a disabled icon', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({ id: 'f00000000009', filename: 'Loi.pdf', status: 'error' })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Loi.pdf' });
    await act(async () => {}); // let the InlineTip -> FloatingTip remount settle before grabbing the button
    await userEvent.setup().hover(screen.getByRole('button', { name: t('action.view') }));
    const tip = await screen.findByTestId('popover-content-container');
    expect(tip).toHaveTextContent(t('action.noTranslation.error'));
  });

  it('keeps the same five slots on every row, with ↻ Dịch lại in the same slot of every row', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([
        fileItem({ id: 'f00000000001', filename: 'Xong.pdf', status: 'done' }),
        fileItem({ id: 'f00000000003', filename: 'Loi.pdf', status: 'error' }),
        fileItem({ id: 'f00000000005', filename: 'Cho.pdf', status: 'queued' }),
      ]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Xong.pdf' });
    await act(async () => {}); // InlineTip -> FloatingTip remount settles before we look inside the slots
    const slots = (name: string) => Array.from(rowOf(name).querySelectorAll('[data-testid="action-slot"]'));
    for (const name of ['Xong.pdf', 'Loi.pdf', 'Cho.pdf']) {
      expect(slots(name)).toHaveLength(5);
      expect(within(slots(name)[3] as HTMLElement).getByRole('button', { name: t('action.retranslate') })).toBeInTheDocument();
    }
  });

  it.each(['queued', 'running'] as const)('locks ↻ Dịch lại on a %s row and says why, without opening anything', async (status) => {
    const { calls } = mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({ id: 'f00000000009', filename: 'Cho.pdf', status })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Cho.pdf' });
    await act(async () => {}); // InlineTip -> FloatingTip remount: grab the button only after it settled
    const redo = within(rowOf('Cho.pdf') as HTMLElement).getByRole('button', { name: t('action.retranslate') });
    expect(redo).toHaveAttribute('aria-disabled', 'true');
    expect(redo).not.toBeDisabled(); // vẫn nhận focus / pointer để tooltip hiện lý do
    expect(redo.isConnected).toBe(true);
    redo.focus({ preventScroll: true });
    expect(redo).toHaveFocus();
    const user = userEvent.setup();
    await user.hover(redo);
    await waitFor(() => expect(screen.getAllByTestId('popover-content-container')
      .some((tip) => tip.textContent?.includes(t('action.retranslate.pending')))).toBe(true));
    await user.click(redo);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(calls.filter((call) => call.method !== 'GET')).toHaveLength(0);
  });

  it('keeps Xem and Tải bản dịch while a done file is retranslated (the old translation stays)', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: META },
      'GET /api/files': list([fileItem({
        id: 'f00000000004', filename: 'Dich-lai.pdf', status: 'running', rebuild_font: 'auto', retranslating: true,
        retranslate_to: { language: 'en', engine: 'google_free', model: null, font: 'auto' },
      })]),
    });
    renderHome();
    await screen.findByRole('link', { name: 'Dich-lai.pdf' });
    await act(async () => {});
    const row = within(rowOf('Dich-lai.pdf') as HTMLElement);
    expect(row.getByRole('button', { name: t('action.view') })).not.toHaveAttribute('aria-disabled');
    expect(row.getByRole('link', { name: t('action.downloadTranslated') }))
      .toHaveAttribute('href', '/api/files/f00000000004/download?kind=translated');
    expect(row.getByRole('button', { name: t('action.retranslate') })).toHaveAttribute('aria-disabled', 'true');
  });
});

