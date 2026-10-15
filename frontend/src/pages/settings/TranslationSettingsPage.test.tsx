import { act, cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAuth } from '../../auth/RequireAuth';
import { AppShell } from '../../components/AppShell';
import { resetMetaCache } from '../../files/useMeta';
import { t } from '../../i18n/t';
import { formatRelative } from '../../lib/relativeTime';
import { STYLE_DEFAULTS, styleOf } from '../../files/profiles';
import { ENGINES, GEMINI_CREDENTIAL, ME, META, MY_PROFILE, SEEDED_PROFILES, SETTINGS, SETTINGS_WITH_GEMINI, SIGNED_IN, filePage, settingsWith } from '../../test/fixtures';
import { bodies, holdRequests, mockApi, sequence } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { SettingsLayout } from './SettingsLayout';
import { TranslationSettingsPage } from './TranslationSettingsPage';

const GEMINI = 'Gemini (Google AI Studio)';
const CLOUD = 'Google Cloud Translation';
const KEY_PUT = 'PUT /api/settings/credentials/gemini';
const TECHNICAL = SEEDED_PROFILES[2];

function renderSettings(at = '/settings/translation') {
  return renderApp(
    <Routes>
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/" element={<p>trang chính</p>} />
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="translation" element={<TranslationSettingsPage />} />
        </Route>
      </Route>
    </Routes>,
    { at },
  );
}

const keyInputs = () => screen.getAllByLabelText(t('settings.key.label'));
const saveButtons = () => screen.getAllByRole('button', { name: t('settings.key.submit') });

beforeEach(() => resetMetaCache());

describe('TranslationSettingsPage loading', () => {
  it('shows skeleton cards, not a spinner, while loading and keeps the page frame', async () => {
    const { fetchMock } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } });
    const hold = holdRequests(fetchMock, '/api/settings');
    renderSettings();
    expect(await screen.findByRole('heading', { name: t('settings.title') })).toBeInTheDocument();
    expect(screen.getAllByRole('status', { name: t('common.loading') })).toHaveLength(3);
    expect(screen.queryByRole('heading', { name: GEMINI })).not.toBeInTheDocument();
    await act(async () => hold.release());
    expect(await screen.findByRole('heading', { name: GEMINI })).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: t('common.loading') })).not.toBeInTheDocument();
  });

  it('renders the cached settings at once on a revisit, then refreshes them', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } });
    renderSettings();
    expect(await screen.findByRole('heading', { name: GEMINI })).toBeInTheDocument();
    cleanup();

    const { fetchMock } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI } });
    const hold = holdRequests(fetchMock, '/api/settings');
    renderSettings();
    expect(await screen.findByRole('heading', { name: GEMINI })).toBeInTheDocument(); // từ bộ nhớ đệm, /api/settings còn bị giữ
    expect(screen.queryByRole('status', { name: t('common.loading') })).not.toBeInTheDocument();
    expect(screen.getAllByText(t('settings.key.none'))).toHaveLength(2);
    await act(async () => hold.release());
    expect(await screen.findByText(t('settings.key.saved', { hint: GEMINI_CREDENTIAL.hint, time: formatRelative(GEMINI_CREDENTIAL.verified_at) }))).toBeInTheDocument();
  });
});

describe('TranslationSettingsPage', () => {
  it('shows both key cards with no key and plain mode by default', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } });
    renderSettings();
    expect(await screen.findByRole('heading', { name: GEMINI })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: CLOUD })).toBeInTheDocument();
    expect(screen.getAllByText(t('settings.key.none'))).toHaveLength(2);
    expect(screen.getByLabelText(t('mode.plain'))).toBeChecked();
    expect(screen.getByLabelText(t('mode.ai'))).toBeDisabled();
    expect(screen.getByLabelText('Google miễn phí')).toBeChecked();
    expect(screen.getByLabelText(CLOUD)).toBeDisabled();
    expect(screen.getByText(t('settings.needKey'))).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: t('settings.key.getKey') });
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      'https://aistudio.google.com/apikey', 'https://console.cloud.google.com/apis/credentials',
    ]);
    expect(keyInputs()[0]).toHaveAttribute('type', 'password');
    // Trình duyệt / trình quản lý mật khẩu không được tự điền mật khẩu đăng nhập vào ô API key.
    for (const input of keyInputs()) {
      expect(input).toHaveAttribute('autocomplete', 'new-password');
      expect(input).toHaveAttribute('data-1p-ignore');
      expect(input).toHaveAttribute('data-lpignore', 'true');
    }
    expect(screen.queryByRole('button', { name: t('settings.key.delete') })).not.toBeInTheDocument();
  });

  it('reaches settings from the avatar menu', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS }, 'GET /api/files': { body: filePage([]) } });
    renderSettings('/');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('shell.accountMenu') }));
    await user.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: t('shell.translationSettings') }));
    expect(await screen.findByRole('heading', { name: t('settings.title') })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/settings/translation');
  });

  it('saves and verifies a Gemini key and switches the default to AI', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS },
      [KEY_PUT]: { body: SETTINGS_WITH_GEMINI },
    });
    renderSettings();
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: GEMINI });
    expect(saveButtons()[0]).toBeDisabled(); // chưa gõ gì
    await user.type(keyInputs()[0], 'AIza-test-key-abcd');
    await user.click(saveButtons()[0]);
    expect(await screen.findByText(t('settings.key.ok'))).toBeInTheDocument();
    expect(screen.getByText('Đã chuyển chế độ mặc định sang Dịch bằng AI (Gemini 3.5 Flash-Lite).')).toBeInTheDocument();
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(put.url).toBe('/api/settings/credentials/gemini');
    expect(JSON.parse(put.body as string)).toEqual({ api_key: 'AIza-test-key-abcd' });
    expect(screen.getByText(t('settings.key.saved', { hint: 'abcd', time: formatRelative(GEMINI_CREDENTIAL.verified_at) }))).toBeInTheDocument();
    expect(screen.getByLabelText(t('mode.ai'))).toBeChecked();
    expect(screen.getByLabelText(t('settings.model'))).toHaveValue('gemini-3.5-flash-lite');
    expect(keyInputs()[0]).toHaveValue('');
    expect(screen.getByRole('button', { name: t('settings.key.delete') })).toBeInTheDocument();
  });

  it('shows why a key was rejected and keeps the form usable', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS },
      [KEY_PUT]: { status: 400, body: { detail: { code: 'invalid_api_key' } } },
    });
    renderSettings();
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: GEMINI });
    await user.type(keyInputs()[0], 'AIza-sai-key-0000');
    await user.click(saveButtons()[0]);
    expect(await screen.findByText(t('error.invalid_api_key'))).toBeInTheDocument();
    expect(saveButtons()[0]).toBeEnabled();
    expect(screen.getAllByText(t('settings.key.none'))).toHaveLength(2);
    expect(screen.getByLabelText(t('mode.ai'))).toBeDisabled();
  });

  it.each([
    ['api_not_enabled', 'API chưa được bật cho project của key này. Bật Cloud Translation API / Generative Language API trong Google Cloud Console.'],
    ['billing_disabled', 'Project của key chưa bật thanh toán.'],
    ['key_restricted', 'Key đang bị giới hạn (theo API, IP hoặc website). Bỏ giới hạn hoặc cho phép API này.'],
    ['provider_rejected', 'Dịch vụ từ chối yêu cầu. Thử model khác hoặc kiểm tra lại cấu hình key.'],
  ])('explains a %s rejection instead of calling the key wrong', async (code, message) => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS },
      [KEY_PUT]: { status: 400, body: { detail: { code } } },
    });
    renderSettings();
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: GEMINI });
    await user.type(keyInputs()[0], 'AIza-test-key-0000');
    await user.click(saveButtons()[0]);
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText(t('error.invalid_api_key'))).not.toBeInTheDocument();
  });

  it('deletes a key after confirmation and falls back to plain mode', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      'GET /api/settings': sequence({ body: SETTINGS_WITH_GEMINI }, { body: SETTINGS }),
      'DELETE /api/settings/credentials/gemini': { status: 204 },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeChecked();
    await user.click(screen.getByRole('button', { name: t('settings.key.delete') }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('settings.key.deleteBody', { label: GEMINI }))).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: t('settings.key.delete') }));
    await vi.waitFor(() => expect(screen.getByLabelText(t('mode.plain'))).toBeChecked());
    expect(screen.getAllByText(t('settings.key.none'))).toHaveLength(2);
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/settings/credentials/gemini')).toBe(true);
  });

  it('saves the default mode and model', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META },
      'GET /api/settings': { body: settingsWith({
        engines: SETTINGS_WITH_GEMINI.engines, gemini_models: SETTINGS_WITH_GEMINI.gemini_models, credentials: [GEMINI_CREDENTIAL],
      }) },
      'PUT /api/settings/preferences': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, default_model: 'gemini-3.8-flash' }) },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByLabelText(t('mode.plain'))).toBeChecked();
    await user.click(screen.getByLabelText(t('mode.ai')));
    await user.selectOptions(screen.getByLabelText(t('settings.model')), 'gemini-3.8-flash');
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(put.url).toBe('/api/settings/preferences');
    expect(JSON.parse(put.body as string)).toEqual({ default_engine: 'gemini', default_model: 'gemini-3.8-flash', default_font: 'auto', advance_mode: false, default_profile: null });
    expect(screen.getByLabelText(t('settings.model'))).toHaveValue('gemini-3.8-flash');
  });

  it('shows the advanced controls only in AI mode, says "Bấm Lưu để áp dụng" until the toggle is saved, then refreshes the signed-in user', async () => {
    const withKey = settingsWith({ engines: SETTINGS_WITH_GEMINI.engines, gemini_models: SETTINGS_WITH_GEMINI.gemini_models, credentials: [GEMINI_CREDENTIAL] });
    const saved = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES, default_profile: TECHNICAL.id });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: withKey }, 'PUT /api/settings/preferences': { body: saved },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByLabelText(t('mode.plain'))).toBeChecked();
    expect(screen.queryByRole('checkbox', { name: t('settings.advance.toggle') })).not.toBeInTheDocument(); // dịch thuần: không có công tắc
    await user.click(screen.getByLabelText(t('mode.ai')));
    const toggle = screen.getByRole('checkbox', { name: t('settings.advance.toggle') });
    expect(toggle).not.toBeChecked();
    expect(screen.getByLabelText(t('settings.advance.defaultProfile'))).toBeDisabled();
    expect(screen.queryByText(t('settings.advance.unsaved'))).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('settings.advance.editProfile') })).not.toBeInTheDocument(); // công tắc tắt: ẩn hẳn
    expect(screen.queryByRole('button', { name: t('settings.advance.newProfile') })).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText(t('settings.advance.unsaved'))).toBeInTheDocument(); // gạt mà chưa Lưu
    expect(screen.getByRole('button', { name: t('settings.advance.editProfile') })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('settings.advance.newProfile') })).toBeInTheDocument();
    const select = screen.getByLabelText(t('settings.advance.defaultProfile'));
    expect(select).toBeEnabled();
    expect(within(select).getAllByRole('option')[0]).toHaveTextContent(t('profiles.none'));
    await user.selectOptions(select, 'preset:technical');
    const meCalls = () => calls.filter((call) => call.url === '/api/auth/me').length;
    const before = meCalls();
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    expect(bodies(calls, 'PUT', '/api/settings/preferences')).toEqual([{
      default_engine: 'gemini', default_model: 'gemini-3.5-flash-lite', default_font: 'auto', advance_mode: true, default_profile: 'preset:technical',
    }]);
    await waitFor(() => expect(meCalls()).toBe(before + 1)); // refreshUser: tab Hồ sơ dịch hiện theo me.advance_mode
    expect(screen.queryByText(t('settings.advance.unsaved'))).not.toBeInTheDocument(); // đã lưu
    expect(screen.getByLabelText(t('settings.advance.defaultProfile'))).toHaveValue(TECHNICAL.id); // server đã gieo và ánh xạ preset: → dòng
  });

  it('switching the default from AI to plain picks Google free, not the AI engine', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI },
      'PUT /api/settings/preferences': { body: SETTINGS },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeChecked();
    await user.click(screen.getByLabelText(t('mode.plain')));
    expect(screen.queryByText(t('settings.advance.plainTurnsOff'))).not.toBeInTheDocument(); // chế độ đã lưu là tắt: không có gì để cảnh báo
    expect(screen.getByLabelText('Google miễn phí')).toBeChecked();
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(JSON.parse(put.body as string)).toEqual({ default_engine: 'google_free', default_model: null, default_font: 'auto', advance_mode: false, default_profile: null });
  });

  it('saves the translated-text font together with the default mode', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS },
      'PUT /api/settings/preferences': { body: settingsWith({ default_font: 'serif' }) },
    });
    renderSettings();
    const user = userEvent.setup();
    const select = await screen.findByLabelText(t('font.field'));
    expect(select).toHaveValue('auto');
    expect(screen.getByRole('option', { name: t('font.serif') })).toBeInTheDocument();
    await user.selectOptions(select, 'serif');
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(JSON.parse(put.body as string)).toEqual({ default_engine: 'google_free', default_model: null, default_font: 'serif', advance_mode: false, default_profile: null });
    expect(screen.getByLabelText(t('font.field'))).toHaveValue('serif');
  });

  it('keeps an unsaved font pick across a key save and sends exactly what the select shows', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS },
      [KEY_PUT]: { body: SETTINGS_WITH_GEMINI }, // default_font vẫn 'auto' trên server
      'PUT /api/settings/preferences': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, default_font: 'serif' }) },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('font.field')), 'serif');
    await user.type(keyInputs()[0], 'AIza-test-key-abcd');
    await user.click(saveButtons()[0]);
    expect(await screen.findByText(t('settings.key.ok'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('font.field'))).toHaveValue('serif');
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    const put = calls.find((call) => call.url === '/api/settings/preferences')!;
    expect(JSON.parse(put.body as string).default_font).toBe('serif');
    expect(screen.getByLabelText(t('font.field'))).toHaveValue('serif');
  });

  it('after a key save the model select shows the model that "Lưu" will send', async () => {
    const withCloud = settingsWith({
      ...SETTINGS_WITH_GEMINI,
      engines: ENGINES.map((engine) => ({ ...engine, available: true })),
      credentials: [GEMINI_CREDENTIAL, { provider: 'google_cloud', hint: 'wxyz', verified_at: GEMINI_CREDENTIAL.verified_at, models: [] }],
    });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI },
      'PUT /api/settings/credentials/google_cloud': { body: withCloud }, // cùng danh sách model + cùng default_model
      'PUT /api/settings/preferences': { body: withCloud },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('settings.model')), 'gemini-3.8-flash');
    await user.type(keyInputs()[1], 'cloud-key-wxyz');
    await user.click(saveButtons()[1]);
    expect(await screen.findByText(t('settings.key.ok'))).toBeInTheDocument();
    const shown = (screen.getByLabelText(t('settings.model')) as HTMLSelectElement).value;
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    const put = calls.find((call) => call.url === '/api/settings/preferences')!;
    expect(JSON.parse(put.body as string).default_model).toBe(shown);
  });

  it('shows the saved key hint and lets the user replace it', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI },
      [KEY_PUT]: { body: settingsWith({ ...SETTINGS_WITH_GEMINI, credentials: [{ ...GEMINI_CREDENTIAL, hint: '9999' }] }) },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByText(t('settings.key.saved', { hint: 'abcd', time: formatRelative(GEMINI_CREDENTIAL.verified_at) }))).toBeInTheDocument();
    expect(screen.getByText(t('settings.key.replaceHint'))).toBeInTheDocument();
    expect(screen.getByText(t('settings.key.privacy'))).toBeInTheDocument();
    await user.type(keyInputs()[0], 'AIza-key-moi-9999');
    await user.click(saveButtons()[0]);
    expect(await screen.findByText(t('settings.key.saved', { hint: '9999', time: formatRelative(GEMINI_CREDENTIAL.verified_at) }))).toBeInTheDocument();
    expect(screen.getByText(t('settings.key.ok'))).toBeInTheDocument();
    // Mặc định vốn đã là AI: không có gì "được chuyển".
    expect(screen.queryByText(/Đã chuyển chế độ mặc định/)).not.toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(1);
  });

  it('hides the advanced controls in plain mode, warns that saving turns the mode off, and sends advance_mode false', async () => {
    const on = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: on },
      'PUT /api/settings/preferences': { body: settingsWith({ ...on, default_engine: 'google_free', default_model: null, advance_mode: false }) },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByRole('checkbox', { name: t('settings.advance.toggle') })).toBeChecked();
    await user.click(screen.getByLabelText(t('mode.plain')));
    expect(screen.queryByRole('checkbox', { name: t('settings.advance.toggle') })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(t('settings.advance.defaultProfile'))).not.toBeInTheDocument();
    expect(screen.getByText(t('settings.advance.plainTurnsOff'))).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    expect(bodies(calls, 'PUT', '/api/settings/preferences')).toEqual([
      { default_engine: 'google_free', default_model: null, default_font: 'auto', advance_mode: false, default_profile: null },
    ]);
    expect(screen.queryByText(t('settings.advance.plainTurnsOff'))).not.toBeInTheDocument(); // server đã tắt
  });

  it('edits the selected default profile in place without touching unsaved picks', async () => {
    const on = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES, default_profile: TECHNICAL.id });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: on },
      [`PUT /api/profiles/${TECHNICAL.id}`]: { body: { ...TECHNICAL, name: 'Kỹ thuật B2B' } },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('font.field')), 'serif'); // lựa chọn dở, chưa Lưu
    await user.click(screen.getByRole('button', { name: t('settings.advance.editProfile') }));
    const form = within(await screen.findByTestId('profile-draft'));
    expect(form.getByText(t('profiles.form.editTitle', { name: 'Tài liệu kỹ thuật' }))).toBeInTheDocument();
    expect(form.getByLabelText(t('profiles.form.name'))).toHaveValue('Tài liệu kỹ thuật');
    expect(form.getByLabelText(t('profiles.field.terms'))).toHaveValue('keep');
    await user.clear(form.getByLabelText(t('profiles.form.name')));
    await user.type(form.getByLabelText(t('profiles.form.name')), 'Kỹ thuật B2B');
    await user.click(form.getByRole('button', { name: t('profiles.form.save') }));
    await waitFor(() => expect(bodies(calls, 'PUT', `/api/profiles/${TECHNICAL.id}`)).toEqual([{ name: 'Kỹ thuật B2B', ...styleOf(TECHNICAL) }]));
    await waitFor(() => expect(screen.queryByTestId('profile-draft')).not.toBeInTheDocument());
    expect(screen.getByLabelText(t('font.field'))).toHaveValue('serif'); // không reset lựa chọn dở
    expect(within(screen.getByLabelText(t('settings.advance.defaultProfile'))).getByRole('option', { name: 'Kỹ thuật B2B' })).toBeInTheDocument();
    expect(screen.getByLabelText(t('settings.advance.defaultProfile'))).toHaveValue(TECHNICAL.id);
    expect(calls.filter((call) => call.url === '/api/settings/preferences')).toHaveLength(0); // chưa Lưu cài đặt
  });

  it('creates a new profile in place and selects it as the default to save', async () => {
    const on = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES });
    const created = { ...MY_PROFILE, id: 'p00000000002', name: 'Hợp đồng API', tone: 'friendly' };
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: on }, 'POST /api/profiles': { status: 201, body: created },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('settings.advance.newProfile') }));
    const form = within(await screen.findByTestId('profile-draft'));
    expect(form.getByText(t('profiles.form.createTitle'))).toBeInTheDocument();
    expect(form.getByRole('button', { name: t('profiles.form.save') })).toBeDisabled(); // chưa có tên
    await user.type(form.getByLabelText(t('profiles.form.name')), 'Hợp đồng API');
    await user.selectOptions(form.getByLabelText(t('profiles.field.tone')), 'friendly');
    await user.click(form.getByRole('button', { name: t('profiles.form.save') }));
    await waitFor(() => expect(bodies(calls, 'POST', '/api/profiles')).toEqual([{ name: 'Hợp đồng API', ...STYLE_DEFAULTS, tone: 'friendly' }]));
    await waitFor(() => expect(screen.getByLabelText(t('settings.advance.defaultProfile'))).toHaveValue('p00000000002')); // chọn luôn hồ sơ mới
    expect(screen.queryByTestId('profile-draft')).not.toBeInTheDocument();
  });

  it('keeps Sửa disabled with no profile selected', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) } });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByRole('button', { name: t('settings.advance.editProfile') })).toBeDisabled(); // "Không áp hồ sơ"
    await user.selectOptions(screen.getByLabelText(t('settings.advance.defaultProfile')), 'preset:quick');
    expect(screen.getByRole('button', { name: t('settings.advance.editProfile') })).toBeEnabled(); // mẫu trong code: Sửa tự gieo rồi mở
    expect(screen.getByRole('button', { name: t('settings.advance.newProfile') })).toBeEnabled();
  });

  it('seeds the presets when Sửa is clicked on a code preset, then edits the seeded row without touching unsaved picks', async () => {
    const unseeded = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true });
    const seeded = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': sequence({ body: unseeded }, { body: unseeded }, { body: seeded }),
      'POST /api/profiles/restore-presets': { body: { updated: 0, created: 5 } },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('font.field')), 'serif');
    await user.selectOptions(screen.getByLabelText(t('settings.advance.defaultProfile')), 'preset:technical');
    await user.click(screen.getByRole('button', { name: t('settings.advance.editProfile') }));
    const form = within(await screen.findByTestId('profile-draft'));
    expect(form.getByText(t('profiles.form.editTitle', { name: 'Tài liệu kỹ thuật' }))).toBeInTheDocument();
    expect(form.getByLabelText(t('profiles.form.name'))).toHaveValue('Tài liệu kỹ thuật');
    expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles/restore-presets')).toHaveLength(1);
    expect(calls.filter((call) => call.method === 'GET' && call.url === '/api/settings')).toHaveLength(3); // tải trang, kiểm lại, sau khi gieo
    expect(screen.getByLabelText(t('settings.advance.defaultProfile'))).toHaveValue(TECHNICAL.id); // dòng đã gieo, không còn preset:technical
    expect(screen.getByLabelText(t('font.field'))).toHaveValue('serif'); // lựa chọn dở giữ nguyên
    expect(calls.filter((call) => call.url === '/api/settings/preferences')).toHaveLength(0);
  });

  it('does not reset profiles seeded elsewhere when Sửa is clicked on a stale code preset: it opens the seeded row as it is now', async () => {
    const unseeded = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true });
    // Trang mở từ trước; trong lúc đó tab khác đã gieo và sửa dòng "Tài liệu kỹ thuật".
    const edited = { ...TECHNICAL, name: 'Kỹ thuật của tôi', tone: 'friendly' };
    const seeded = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES.map((row) => (row.id === TECHNICAL.id ? edited : row)) });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': sequence({ body: unseeded }, { body: seeded }),
      'POST /api/profiles/restore-presets': { body: { updated: 5, created: 0 } },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('settings.advance.defaultProfile')), 'preset:technical');
    await user.click(screen.getByRole('button', { name: t('settings.advance.editProfile') }));
    const form = within(await screen.findByTestId('profile-draft'));
    expect(form.getByText(t('profiles.form.editTitle', { name: 'Kỹ thuật của tôi' }))).toBeInTheDocument();
    expect(form.getByLabelText(t('profiles.form.name'))).toHaveValue('Kỹ thuật của tôi');
    expect(form.getByLabelText(t('profiles.field.tone'))).toHaveValue('friendly'); // bản sửa còn nguyên, không bị đưa về mẫu
    expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles/restore-presets')).toHaveLength(0);
    expect(screen.getByLabelText(t('settings.advance.defaultProfile'))).toHaveValue(TECHNICAL.id);
  });

  it('says the profile is gone, without seeding, when the stale code preset was already seeded and that row deleted elsewhere', async () => {
    const unseeded = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true });
    const seeded = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES.filter((row) => row.id !== TECHNICAL.id) });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': sequence({ body: unseeded }, { body: seeded }),
      'POST /api/profiles/restore-presets': { body: { updated: 4, created: 1 } },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('settings.advance.defaultProfile')), 'preset:technical');
    await user.click(screen.getByRole('button', { name: t('settings.advance.editProfile') }));
    expect(await within(await screen.findByTestId('profile-draft')).findByText(t('error.profile_not_found'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles/restore-presets')).toHaveLength(0);
  });

  it('shows the server reason inside the draft area when seeding for Sửa is refused', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) },
      'POST /api/profiles/restore-presets': { status: 409, body: { detail: { code: 'too_many_profiles', limit: 20 } } },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(t('settings.advance.defaultProfile')), 'preset:technical');
    await user.click(screen.getByRole('button', { name: t('settings.advance.editProfile') }));
    // Câu riêng cho "không đủ chỗ gieo mẫu" — "Bạn đã có 20 hồ sơ" là sai với người có 16–19 hồ sơ.
    expect(await within(await screen.findByTestId('profile-draft')).findByText(t('error.presets_no_room', { limit: 20 }))).toBeInTheDocument();
    expect(screen.queryByText(t('error.too_many_profiles', { limit: 20 }))).not.toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles/restore-presets')).toHaveLength(1);
    expect(calls.filter((call) => call.method === 'GET' && call.url === '/api/settings')).toHaveLength(2); // tải trang + kiểm lại; không tải sau lỗi
  });

  it('shows the server reason inside the in-place form when the profile save is refused', async () => {
    mockApi({
      ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES }) },
      'POST /api/profiles': { status: 409, body: { detail: { code: 'too_many_profiles', limit: 20 } } },
    });
    renderSettings();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('settings.advance.newProfile') }));
    const form = within(await screen.findByTestId('profile-draft'));
    await user.type(form.getByLabelText(t('profiles.form.name')), 'Thừa');
    await user.click(form.getByRole('button', { name: t('profiles.form.save') }));
    expect(await form.findByText(t('error.too_many_profiles', { limit: 20 }))).toBeInTheDocument();
    expect(screen.getByTestId('profile-draft')).toBeInTheDocument(); // form còn mở để sửa
  });

  it('deleting the Gemini key warns that advanced mode turns off, then drops the Profiles tab at once', async () => {
    const on = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, profiles: SEEDED_PROFILES });
    const off = settingsWith({ profiles: SEEDED_PROFILES });
    const { calls } = mockApi({
      ...SIGNED_IN, 'GET /api/auth/me': sequence({ body: { ...ME, advance_mode: true } }, { body: ME }),
      'GET /api/meta': { body: META }, 'GET /api/settings': sequence({ body: on }, { body: off }),
      'DELETE /api/settings/credentials/gemini': { status: 204 },
    });
    renderSettings();
    const user = userEvent.setup();
    expect(await screen.findByRole('link', { name: t('settings.tab.profiles') })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: t('settings.key.delete') }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('settings.key.deleteTurnsOffAdvance'))).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: t('settings.key.delete') }));
    await waitFor(() => expect(screen.queryByRole('link', { name: t('settings.tab.profiles') })).not.toBeInTheDocument());
    expect(screen.queryByRole('checkbox', { name: t('settings.advance.toggle') })).not.toBeInTheDocument();
    expect(calls.filter((call) => call.url === '/api/auth/me')).toHaveLength(2);
  });

  it('does not warn about advanced mode in the delete-key dialog when it is off', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI } });
    renderSettings();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('settings.key.delete') }));
    expect(within(await screen.findByRole('dialog')).queryByText(t('settings.key.deleteTurnsOffAdvance'))).not.toBeInTheDocument();
  });
});
