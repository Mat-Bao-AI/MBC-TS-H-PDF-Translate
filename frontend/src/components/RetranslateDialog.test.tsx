import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RetranslateChoice } from '../api/files';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SETTINGS, SETTINGS_WITH_GEMINI, SIGNED_IN, fileItem, settingsWith } from '../test/fixtures';
import { mockApi } from '../test/mockApi';
import { renderApp } from '../test/render';
import { RetranslateDialog, type RetranslateTarget } from './RetranslateDialog';

/** Hộp mở sẵn; Huỷ / xác nhận đóng nó như trang cha thật (onClose → target null). */
function Harness({ target, onConfirm }: { target: RetranslateTarget; onConfirm: (settings: RetranslateChoice | null) => void }) {
  const [open, setOpen] = useState(true);
  return <RetranslateDialog target={open ? target : null} onClose={() => setOpen(false)} onConfirm={onConfirm} />;
}

const renderDialog = (target: RetranslateTarget, onConfirm = vi.fn()) => {
  renderApp(<Harness target={target} onConfirm={onConfirm} />);
  return onConfirm;
};

beforeEach(() => resetMetaCache());

describe('RetranslateDialog', () => {
  it("prefills a done file's language, AI model and font, warns about the cost and sends the four choices", async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI } });
    const onConfirm = renderDialog({ item: fileItem({ filename: 'Hợp đồng.pdf', language: 'en', engine: 'gemini', model: 'gemini-3.8-flash', font: 'serif' }) });
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.title', { name: 'Hợp đồng.pdf' }))).toBeInTheDocument();
    expect(dialog.getByText(t('retranslate.warnDone'))).toBeInTheDocument();
    expect(await dialog.findByLabelText(t('upload.model'))).toHaveValue('gemini-3.8-flash');
    expect(dialog.getByLabelText(t('mode.ai'))).toBeChecked();
    await waitFor(() => expect(dialog.getByLabelText(t('upload.language'))).toHaveValue('en'));
    expect(dialog.getByLabelText(t('font.field'))).toHaveValue('serif');
    // Dialog của Gamut không tự cuộn: vùng trường cuộn riêng để nút xác nhận không rơi khỏi màn hình thấp.
    expect(getComputedStyle(dialog.getByTestId('retranslate-fields')).overflowY).toBe('auto');
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith({ language: 'en', engine: 'gemini', model: 'gemini-3.8-flash', font: 'serif' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('prefills a failed file in plain mode with its engine and says that finished passages are reused', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } });
    renderDialog({ item: fileItem({ status: 'error', language: 'en', engine: 'google_free', font: 'sans' }) });
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.warnError'))).toBeInTheDocument();
    expect(dialog.queryByText(t('retranslate.warnDone'))).not.toBeInTheDocument();
    expect(await dialog.findByLabelText('Google miễn phí')).toBeChecked();
    expect(dialog.getByLabelText(t('mode.plain'))).toBeChecked();
    expect(dialog.getByLabelText(t('font.field'))).toHaveValue('sans');
  });

  it("falls back to the default model when the file's model is no longer offered for the key", async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.1-pro-preview' }) });
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByLabelText(t('upload.model'))).toHaveValue('gemini-3.5-flash-lite');
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith({ language: 'vi', engine: 'gemini', model: 'gemini-3.5-flash-lite', font: 'auto' });
  });

  it("keeps each file's own settings by default for many files", async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } });
    const onConfirm = renderDialog({ count: 27 });
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('retranslate.bulkTitle', { n: 27 }))).toBeInTheDocument();
    expect(dialog.getByText(`${t('retranslate.warnDone')} ${t('retranslate.warnQueue')}`)).toBeInTheDocument();
    expect(dialog.getByLabelText(t('retranslate.scope.keep'))).toBeChecked();
    expect(dialog.queryByLabelText(t('upload.language'))).not.toBeInTheDocument();
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it('applies one choice to many files, prefilled from the meta language and the saved defaults', async () => {
    mockApi({
      ...SIGNED_IN,
      'GET /api/meta': { body: { ...META, default_language: 'en' } },
      'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, default_font: 'serif' }) },
    });
    const onConfirm = renderDialog({ count: 3 });
    const dialog = within(await screen.findByRole('dialog'));
    const user = userEvent.setup();
    await user.click(dialog.getByLabelText(t('retranslate.scope.apply')));
    expect(await dialog.findByLabelText(t('upload.model'))).toHaveValue('gemini-3.5-flash-lite');
    await waitFor(() => expect(dialog.getByLabelText(t('upload.language'))).toHaveValue('en'));
    expect(dialog.getByLabelText(t('font.field'))).toHaveValue('serif');
    await user.click(dialog.getByLabelText(t('mode.plain')));
    await user.selectOptions(dialog.getByLabelText(t('upload.language')), 'vi');
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith({ language: 'vi', engine: 'google_free', model: null, font: 'serif' });
  });

  it('keeps Dịch lại locked until the settings are known and says when they cannot be loaded', async () => {
    const { fetchMock } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META } });
    const answer = fetchMock.getMockImplementation()!;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    fetchMock.mockImplementation(async (input, init) => {
      if (input === '/api/settings') {
        await gate; // treo tới khi test cho trả lời: thấy được trạng thái "đang tải"
        return new Response(JSON.stringify({ detail: { code: 'unknown' } }), { status: 500, headers: { 'Content-Type': 'application/json' } });
      }
      return answer(input, init);
    });
    const onConfirm = renderDialog({ item: fileItem() });
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByRole('button', { name: t('retranslate.confirm') })).toBeDisabled();
    await act(async () => { release(); });
    expect(await dialog.findByText(t('settings.loadError'))).toBeInTheDocument();
    expect(dialog.getByRole('button', { name: t('retranslate.confirm') })).toBeDisabled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
