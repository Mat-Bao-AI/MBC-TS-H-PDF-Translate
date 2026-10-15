import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RetranslateRequest } from '../api/files';
import { styleOf } from '../files/profiles';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, MY_PROFILE, PRESETS, SEEDED_PROFILES, SETTINGS, SETTINGS_WITH_GEMINI, SIGNED_IN, fileItem, settingsWith, snapshot } from '../test/fixtures';
import { TRANSLATION_SETTINGS_CACHE_KEY } from '../api/settings';
import { cacheGet, cacheSet } from '../lib/swrCache';
import { mockApi } from '../test/mockApi';
import { renderApp } from '../test/render';
import { RetranslateDialog, type RetranslateTarget } from './RetranslateDialog';

/** Hộp mở sẵn; Huỷ / xác nhận đóng nó như trang cha thật (onClose → target null). */
function Harness({ target, onConfirm }: { target: RetranslateTarget; onConfirm: (settings: RetranslateRequest | null) => void }) {
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
  it('prefills the advanced section from the file snapshot and sends profile, overrides and context with the four choices', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) } });
    const config = snapshot({ style: { ...snapshot().style, tone: 'friendly' }, overrides: ['tone'], document_context: 'Tài liệu API.' });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config }) });
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByLabelText(t('upload.advanced.profile'))).toHaveValue('preset:technical');
    expect(dialog.getByRole('checkbox', { name: t('upload.advanced.customize') })).toBeChecked();
    expect(dialog.getByLabelText(t('profiles.field.tone'))).toHaveValue('friendly');
    expect(dialog.getByLabelText(t('upload.advanced.context'))).toHaveValue('Tài liệu API.');
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith({
      language: 'vi', engine: 'gemini', model: 'gemini-3.5-flash-lite', font: 'auto',
      profile: 'preset:technical', style: { tone: 'friendly' }, context: 'Tài liệu API.',
    });
  });

  it('prefills a deleted profile as no profile with its style as overrides', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) } });
    const gone = snapshot({ profile: { id: 'p00000000009', name: 'Đã xoá', kind: 'custom' } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config: gone }) });
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByLabelText(t('upload.advanced.profile'))).toHaveValue('');
    expect(dialog.getByRole('checkbox', { name: t('upload.advanced.customize') })).toBeChecked();
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    const sent = onConfirm.mock.calls[0][0];
    expect(sent).not.toHaveProperty('profile'); // không hồ sơ: bỏ khoá, không gửi null
    expect(sent.style).toEqual(gone.style);
    expect(sent).not.toHaveProperty('context');
  });

  it('sends only the four choices when the file switches to a plain engine', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config: snapshot() }) });
    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByLabelText(t('upload.advanced.profile'));
    await userEvent.setup().click(dialog.getByLabelText(t('mode.plain')));
    expect(dialog.queryByTestId('retranslate-advanced')).not.toBeInTheDocument();
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith({ language: 'vi', engine: 'google_free', model: null, font: 'auto' });
  });

  it('tells many-file users that each file keeps its own profile and context', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ advance_mode: true }) } });
    renderDialog({ count: 3 });
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByText(t('retranslate.bulkKeepsConfig'))).toBeInTheDocument();
    expect(dialog.queryByLabelText(t('upload.advanced.profile'))).not.toBeInTheDocument();
  });

  it('sends only the four keys when advanced mode is off, even with an AI engine and a snapshot', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config: snapshot() }) });
    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByLabelText(t('upload.model'));
    expect(dialog.queryByTestId('retranslate-advanced')).not.toBeInTheDocument();
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(Object.keys(onConfirm.mock.calls[0][0]).sort()).toEqual(['engine', 'font', 'language', 'model']);
  });

  it('preselects no profile for a basic file even when a default profile is set (spec §8)', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: 'preset:quick' });
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settings } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config: null }) });
    const dialog = within(await screen.findByRole('dialog'));
    expect(await dialog.findByLabelText(t('upload.advanced.profile'))).toHaveValue('');
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(Object.keys(onConfirm.mock.calls[0][0]).sort()).toEqual(['engine', 'font', 'language', 'model']);
  });

  describe('a profile edited after the snapshot', () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: [...PRESETS, MY_PROFILE] });
    const before = { ...styleOf(MY_PROFILE), fidelity: 'literal', audience: 'expert', custom_instructions: 'Bản cũ.' };
    const profile = { id: MY_PROFILE.id, name: MY_PROFILE.name, kind: 'custom' as const };
    const open = (config: ReturnType<typeof snapshot>) => {
      mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settings } });
      return renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config }) });
    };

    it('applies the edited profile when the snapshot had no overrides: only `profile` travels', async () => {
      const onConfirm = open(snapshot({ profile, style: before, overrides: [] }));
      const dialog = within(await screen.findByRole('dialog'));
      expect(await dialog.findByLabelText(t('upload.advanced.profile'))).toHaveValue(MY_PROFILE.id);
      const customize = dialog.getByRole('checkbox', { name: t('upload.advanced.customize') });
      expect(customize).not.toBeChecked();
      const user = userEvent.setup();
      await user.click(customize); // mở ra xem: điền giá trị HIỆN TẠI của hồ sơ, không phải giá trị cũ trong snapshot
      expect(dialog.getByLabelText(t('profiles.field.fidelity'))).toHaveValue(MY_PROFILE.fidelity);
      expect(dialog.getByLabelText(t('profiles.field.custom_instructions'))).toHaveValue(MY_PROFILE.custom_instructions);
      await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
      expect(onConfirm).toHaveBeenCalledWith({ language: 'vi', engine: 'gemini', model: 'gemini-3.5-flash-lite', font: 'auto', profile: MY_PROFILE.id });
    });

    it('keeps only the snapshot overrides on top of the edited profile', async () => {
      const onConfirm = open(snapshot({ profile, style: { ...before, tone: 'simple' }, overrides: ['tone'] }));
      const dialog = within(await screen.findByRole('dialog'));
      expect(await dialog.findByLabelText(t('upload.advanced.profile'))).toHaveValue(MY_PROFILE.id);
      expect(dialog.getByRole('checkbox', { name: t('upload.advanced.customize') })).toBeChecked();
      expect(dialog.getByLabelText(t('profiles.field.tone'))).toHaveValue('simple');
      expect(dialog.getByLabelText(t('profiles.field.fidelity'))).toHaveValue(MY_PROFILE.fidelity);
      await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
      expect(onConfirm).toHaveBeenCalledWith({
        language: 'vi', engine: 'gemini', model: 'gemini-3.5-flash-lite', font: 'auto', profile: MY_PROFILE.id, style: { tone: 'simple' },
      });
    });
  });

  it('omits profile, style and context keys when advanced mode is on but nothing applies', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config: null }) });
    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByLabelText(t('upload.advanced.profile'));
    await userEvent.setup().click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(Object.keys(onConfirm.mock.calls[0][0]).sort()).toEqual(['engine', 'font', 'language', 'model']);
  });

  it('saves the customised fields as a new profile from the retranslate dialog and sends the new profile id', async () => {
    const technical = SEEDED_PROFILES[2];
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES });
    cacheSet(TRANSLATION_SETTINGS_CACHE_KEY, settings);
    const created = { ...technical, id: 'p00000000002', name: 'Luận văn', tone: 'academic', preset_slug: null };
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settings }, 'POST /api/profiles': { status: 201, body: created },
    });
    const config = snapshot({ profile: { id: technical.id, name: technical.name, kind: 'custom' } });
    const onConfirm = renderDialog({ item: fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', config }) });
    const dialog = within(await screen.findByRole('dialog'));
    const user = userEvent.setup();
    expect(await dialog.findByLabelText(t('upload.advanced.profile'))).toHaveValue(technical.id);
    await user.click(dialog.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    await user.selectOptions(dialog.getByLabelText(t('profiles.field.tone')), 'academic');
    await user.click(dialog.getByRole('button', { name: t('profiles.saveAsNew') }));
    await user.clear(dialog.getByLabelText(t('profiles.form.name')));
    await user.type(dialog.getByLabelText(t('profiles.form.name')), 'Luận văn');
    await user.click(dialog.getByRole('button', { name: t('profiles.create') }));
    await waitFor(() => expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles')).toHaveLength(1));
    await waitFor(() => expect(dialog.getByLabelText(t('upload.advanced.profile'))).toHaveValue('p00000000002'));
    expect(cacheGet(TRANSLATION_SETTINGS_CACHE_KEY)).toBeUndefined();
    await user.click(dialog.getByRole('button', { name: t('retranslate.confirm') }));
    expect(onConfirm).toHaveBeenCalledWith({ language: 'vi', engine: 'gemini', model: 'gemini-3.5-flash-lite', font: 'auto', profile: 'p00000000002' });
  });
});
