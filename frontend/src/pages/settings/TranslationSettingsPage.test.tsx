import { act, cleanup, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAuth } from '../../auth/RequireAuth';
import { AppShell } from '../../components/AppShell';
import { resetMetaCache } from '../../files/useMeta';
import { t } from '../../i18n/t';
import { formatRelative } from '../../lib/relativeTime';
import { ENGINES, GEMINI_CREDENTIAL, META, SETTINGS, SETTINGS_WITH_GEMINI, SIGNED_IN, filePage, settingsWith } from '../../test/fixtures';
import { holdRequests, mockApi, sequence } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { SettingsLayout } from './SettingsLayout';
import { TranslationSettingsPage } from './TranslationSettingsPage';

const GEMINI = 'Gemini (Google AI Studio)';
const CLOUD = 'Google Cloud Translation';
const KEY_PUT = 'PUT /api/settings/credentials/gemini';

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
    expect(JSON.parse(put.body as string)).toEqual({ default_engine: 'gemini', default_model: 'gemini-3.8-flash', default_font: 'auto' });
    expect(screen.getByLabelText(t('settings.model'))).toHaveValue('gemini-3.8-flash');
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
    expect(screen.getByLabelText('Google miễn phí')).toBeChecked();
    await user.click(screen.getByRole('button', { name: t('settings.save') }));
    expect(await screen.findByText(t('settings.saved'))).toBeInTheDocument();
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(JSON.parse(put.body as string)).toEqual({ default_engine: 'google_free', default_model: null, default_font: 'auto' });
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
    expect(JSON.parse(put.body as string)).toEqual({ default_engine: 'google_free', default_model: null, default_font: 'serif' });
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
});
