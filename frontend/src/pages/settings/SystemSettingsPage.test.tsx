import { act, cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { AdminOnly, RequireAuth } from '../../auth/RequireAuth';
import { AppShell } from '../../components/AppShell';
import { resetMetaCache } from '../../files/useMeta';
import { t } from '../../i18n/t';
import { ADMIN, META, SYSTEM, signedInAs, systemWith } from '../../test/fixtures';
import { holdRequests, mockApi, sequence, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { SettingsLayout } from './SettingsLayout';
import { SystemSettingsPage } from './SystemSettingsPage';

const AS_ADMIN: Record<string, Handler> = { ...signedInAs(ADMIN), 'GET /api/meta': { body: META } };
const fail = (status: number, body: Record<string, unknown>) => ({ status, body: { detail: body } });

function renderSystem(at = '/settings/system') {
  return renderApp(
    <Routes>
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="account" element={<p>thẻ tài khoản</p>} />
          <Route path="system" element={<AdminOnly><SystemSettingsPage /></AdminOnly>} />
        </Route>
      </Route>
    </Routes>,
    { at },
  );
}

const smtpCard = () => within(screen.getByRole('region', { name: t('system.smtp.title') }));
const regCard = () => within(screen.getByRole('region', { name: t('system.registration.title') }));
const putBodies = (calls: { method: string; url: string; body: unknown }[]) =>
  calls.filter((call) => call.method === 'PUT' && call.url === '/api/system/settings').map((call) => JSON.parse(String(call.body)));

/** Khối FormGroup của một ô (nhãn + ô + lỗi): hai cấp trên <input>. */
const fieldGroup = (input: HTMLElement) => input.parentElement!.parentElement!;

beforeEach(() => resetMetaCache());

describe('SystemSettingsPage loading', () => {
  it('shows skeleton cards, not a spinner, while loading and keeps the page frame', async () => {
    const { fetchMock } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM } });
    const hold = holdRequests(fetchMock, '/api/system/settings');
    renderSystem();
    expect(await screen.findByRole('heading', { name: t('settings.title') })).toBeInTheDocument();
    expect(screen.getAllByRole('status', { name: t('common.loading') })).toHaveLength(2);
    await act(async () => hold.release());
    expect(await screen.findByRole('region', { name: t('system.smtp.title') })).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: t('common.loading') })).not.toBeInTheDocument();
  });

  it('renders the cached settings at once on a revisit, then refreshes them', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ max_pending_default: 7 }) } });
    renderSystem();
    expect(await screen.findByRole('region', { name: t('system.smtp.title') })).toBeInTheDocument();
    cleanup();

    const { fetchMock } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ max_pending_default: 9 }) } });
    const hold = holdRequests(fetchMock, '/api/system/settings');
    renderSystem();
    expect(await screen.findByRole('region', { name: t('system.smtp.title') })).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: t('common.loading') })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('7')).toBeInTheDocument();
    await act(async () => hold.release());
    expect(await screen.findByPlaceholderText('9')).toBeInTheDocument();
  });
});

describe('SystemSettingsPage', () => {
  it.each([
    ['settings', 'system.smtp.source.settings'], ['env', 'system.smtp.source.env'],
    ['none', 'system.smtp.source.none'], ['dev_log', 'system.smtp.source.dev_log'],
  ] as const)('tells where the mail configuration comes from (%s)', async (source, key) => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ smtp: { source } }) } });
    renderSystem();
    expect(await screen.findByText(t(key))).toBeInTheDocument();
    expect(smtpCard().getByRole('button', { name: t('system.smtp.clear') })).toHaveProperty('disabled', source !== 'settings');
  });

  it.each([
    ['env', 'system.siteUrl.source.env'], ['setup', 'system.siteUrl.source.setup'],
  ] as const)('shows the site address used in mail and where it comes from (%s)', async (source, key) => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ site_url: 'https://pdf.example', site_url_source: source }) } });
    renderSystem();
    await screen.findByRole('region', { name: t('system.smtp.title') });
    expect(smtpCard().getByText(t('system.siteUrl.known', { url: 'https://pdf.example' }))).toBeInTheDocument();
    expect(smtpCard().getByText(t(key))).toBeInTheDocument();
    const other = source === 'env' ? 'system.siteUrl.source.setup' : 'system.siteUrl.source.env';
    expect(screen.queryByText(t(other))).not.toBeInTheDocument();
    expect(screen.queryByText(t('system.siteUrl.unknown'))).not.toBeInTheDocument();
  });

  it('warns inside the SMTP card when the site address is unknown, without a form field', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ site_url: null, site_url_source: null }) } });
    renderSystem();
    await screen.findByRole('region', { name: t('system.smtp.title') });
    expect(smtpCard().getByText(t('system.siteUrl.unknown'))).toBeInTheDocument();
    expect(screen.queryByText(t('system.siteUrl.source.env'))).not.toBeInTheDocument();
    expect(screen.queryByText(t('system.siteUrl.source.setup'))).not.toBeInTheDocument();
    expect(screen.queryByText(/^Địa chỉ trang dùng trong thư/)).not.toBeInTheDocument();
    // Hành vi, không ghim id: form SMTP vẫn sửa được dù chưa biết địa chỉ trang, cảnh báo vẫn hiện.
    const host = smtpCard().getByLabelText(t('system.smtp.host'));
    await userEvent.setup().type(host, 'smtp.example.com');
    expect(host).toHaveValue('smtp.example.com');
    expect(smtpCard().getByText(t('system.siteUrl.unknown'))).toBeInTheDocument();
  });

  it('prefills the form from the effective configuration and hints that a password is saved', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({
      smtp: { source: 'env', host: 'env.example.com', port: 465, security: 'ssl', username: 'envu', from: 'env@example.com', password_status: 'saved' },
    }) } });
    renderSystem();
    expect(await screen.findByLabelText(t('system.smtp.host'))).toHaveValue('env.example.com');
    expect(screen.getByLabelText(t('system.smtp.port'))).toHaveValue(465);
    expect(screen.getByLabelText(t('system.smtp.security'))).toHaveValue('ssl');
    expect(screen.getByLabelText(t('system.smtp.username'))).toHaveValue('envu');
    expect(screen.getByLabelText(t('system.smtp.password'))).toHaveValue('');
    expect(screen.getByText(t('system.smtp.password.saved'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('system.smtp.from'))).toHaveValue('env@example.com');
  });

  it('warns when the saved password cannot be read any more', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ smtp: { source: 'settings', host: 'db.example.com', password_status: 'unreadable' } }) } });
    renderSystem();
    expect(await screen.findByText(t('system.smtp.password.unreadable'))).toBeInTheDocument();
  });

  it('saves the SMTP card without sending an empty password and refreshes the instance status', async () => {
    const saved = systemWith({ smtp: { source: 'settings', host: 'smtp.example.com', port: 2525, security: 'none', username: 'u', from: 'PDF <no-reply@example.com>', password_status: 'saved' } });
    const { calls } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM }, 'PUT /api/system/settings': { body: saved } });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.clear(screen.getByLabelText(t('system.smtp.port')));
    await user.type(screen.getByLabelText(t('system.smtp.port')), '2525');
    await user.selectOptions(screen.getByLabelText(t('system.smtp.security')), 'none');
    await user.type(screen.getByLabelText(t('system.smtp.username')), 'u');
    await user.type(screen.getByLabelText(t('system.smtp.from')), 'PDF <no-reply@example.com>');
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.save') }));
    expect(await screen.findByText(t('system.smtp.saved'))).toBeInTheDocument();
    expect(putBodies(calls)).toEqual([{ smtp: { host: 'smtp.example.com', port: 2525, security: 'none', username: 'u', from: 'PDF <no-reply@example.com>' } }]);
    expect(screen.getByText(t('system.smtp.source.settings'))).toBeInTheDocument();
    expect(calls.filter((call) => call.url === '/api/setup/status')).toHaveLength(2); // nạp lúc đầu + sau khi lưu
    expect(smtpCard().getByRole('button', { name: t('system.smtp.clear') })).toBeEnabled();
  });

  it('shows a field error from invalid_smtp under the right field', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM }, 'PUT /api/system/settings': fail(422, { code: 'invalid_smtp', field: 'from' }) });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.save') }));
    const message = await screen.findByText(t('system.smtp.invalidField'));  // dưới ô (FormGroup error)
    expect(fieldGroup(screen.getByLabelText(t('system.smtp.from'))).contains(message)).toBe(true);
    expect(fieldGroup(screen.getByLabelText(t('system.smtp.host'))).contains(message)).toBe(false);
    expect(screen.queryByText(t('error.invalid_smtp', { field: 'from' }))).not.toBeInTheDocument();  // không phải Alert chung
  });

  it('sends a test mail with the values in the form and reports success', async () => {
    const { calls } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM }, 'POST /api/system/smtp/test': { body: { sent_to: 'admin@example.com' } } });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'thu.example.com');
    await user.type(screen.getByLabelText(t('system.smtp.password')), 'mat-khau');
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.test') }));
    expect(await screen.findByText(t('system.smtp.testOk', { email: 'admin@example.com' }))).toBeInTheDocument();
    const post = calls.find((call) => call.method === 'POST')!;
    expect(JSON.parse(String(post.body))).toEqual({ smtp: { host: 'thu.example.com', port: 587, security: 'starttls', username: '', from: '', password: 'mat-khau' } });
    expect(putBodies(calls)).toEqual([]); // thử không lưu
  });

  it('reports why the test mail failed', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM }, 'POST /api/system/smtp/test': fail(502, { code: 'smtp_failed', reason: 'SMTPAuthenticationError: (535, ***)' }) });
    renderSystem();
    await screen.findByRole('region', { name: t('system.smtp.title') });
    await userEvent.setup().click(smtpCard().getByRole('button', { name: t('system.smtp.test') }));
    expect(await screen.findByText(t('error.smtp_failed', { reason: 'SMTPAuthenticationError: (535, ***)' }))).toBeInTheDocument();
  });

  it('clears the saved configuration after confirmation and goes back to the environment', async () => {
    const { calls } = mockApi({
      ...AS_ADMIN,
      'GET /api/system/settings': sequence({ body: systemWith({ smtp: { source: 'settings', host: 'db.example.com' } }) }, { body: SYSTEM }),
      'DELETE /api/system/settings/smtp': { status: 204 },
    });
    renderSystem();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('system.smtp.title') });
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.clear') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('system.smtp.clearTitle'))).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: t('system.smtp.clear') }));
    expect(await screen.findByText(t('system.smtp.cleared'))).toBeInTheDocument();
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/system/settings/smtp')).toBe(true);
    expect(screen.getByText(t('system.smtp.source.none'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('system.smtp.host'))).toHaveValue('');
  });

  it('saves the registration switch and the pending limit in one PUT', async () => {
    const { calls } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM },
      'PUT /api/system/settings': { body: systemWith({ registration_open: false, max_pending_per_user: 7 }) } });
    renderSystem();
    const user = userEvent.setup();
    const toggle = await screen.findByRole('checkbox', { name: t('system.registration.open') });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    expect(screen.getByText(t('system.limit.hint', { n: 3 }))).toBeInTheDocument();
    await user.type(screen.getByLabelText(t('system.limit.label')), '7');
    await user.click(regCard().getByRole('button', { name: t('system.registration.save') }));
    expect(await screen.findByText(t('system.registration.saved'))).toBeInTheDocument();
    expect(putBodies(calls)).toEqual([{ registration_open: false, max_pending_per_user: 7, max_versions: null }]);
  });

  it('"Đặt về mặc định" writes null for the limit', async () => {
    const { calls } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ max_pending_per_user: 7 }) },
      'PUT /api/system/settings': { body: SYSTEM } });
    renderSystem();
    const user = userEvent.setup();
    expect(await screen.findByLabelText(t('system.limit.label'))).toHaveValue(7);
    await user.click(regCard().getByRole('button', { name: t('system.limit.reset') }));
    expect(await screen.findByText(t('system.registration.saved'))).toBeInTheDocument();
    expect(putBodies(calls)).toEqual([{ max_pending_per_user: null, max_versions: null }]);
    expect(screen.getByLabelText(t('system.limit.label'))).toHaveValue(null);
  });

  it('"Đặt về mặc định" never saves an unsaved registration switch, and keeps it as edited', async () => {
    const { calls } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ max_pending_per_user: 7 }) },
      'PUT /api/system/settings': { body: SYSTEM } });
    renderSystem();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('checkbox', { name: t('system.registration.open') })); // tắt, CHƯA lưu
    await user.click(regCard().getByRole('button', { name: t('system.limit.reset') }));
    expect(await screen.findByText(t('system.registration.saved'))).toBeInTheDocument();
    expect(putBodies(calls)).toEqual([{ max_pending_per_user: null, max_versions: null }]);
    expect(screen.getByLabelText(t('system.limit.label'))).toHaveValue(null);
    expect(screen.getByRole('checkbox', { name: t('system.registration.open') })).not.toBeChecked();
  });

  it('saves the number of kept versions and shows the default as a placeholder', async () => {
    const { calls } = mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM },
      'PUT /api/system/settings': { body: systemWith({ max_versions: 5 }) } });
    renderSystem();
    const input = await screen.findByLabelText(t('system.versions.label'));
    expect(input).toHaveAttribute('placeholder', '3');
    expect(input).toHaveAttribute('min', '1');
    expect(input).toHaveAttribute('max', '10');
    expect(screen.getByText(t('system.versions.hint', { n: 3 }))).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(input, '5');
    await user.click(regCard().getByRole('button', { name: t('system.registration.save') }));
    await waitFor(() => expect(putBodies(calls)).toEqual([{ registration_open: true, max_pending_per_user: null, max_versions: 5 }]));
    expect(await screen.findByText(t('system.registration.saved'))).toBeInTheDocument();
    expect(input).toHaveValue(5);
  });

  it('puts invalid_max_versions under the versions field and keeps the rest of the card', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM },
      'PUT /api/system/settings': fail(422, { code: 'invalid_max_versions' }) });
    renderSystem();
    const input = await screen.findByLabelText(t('system.versions.label'));
    const user = userEvent.setup();
    await user.type(input, '11');
    await user.click(regCard().getByRole('button', { name: t('system.registration.save') }));
    expect(await within(fieldGroup(input)).findByText(t('error.invalid_max_versions'))).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: t('system.registration.open') })).toBeChecked();
  });

  it('shows invalid_limit under the number field', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM }, 'PUT /api/system/settings': fail(422, { code: 'invalid_limit' }) });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.limit.label')), '101');
    await user.click(regCard().getByRole('button', { name: t('system.registration.save') }));
    expect(await regCard().findByText(t('error.invalid_limit'))).toBeInTheDocument();  // trong thẻ, dưới ô số
    expect(screen.getAllByText(t('error.invalid_limit'))).toHaveLength(1);  // không hiện thêm ở Alert chung
  });

  it('sends a non-admin who types the URL to the account tab', async () => {
    mockApi({ ...signedInAs({ is_admin: false }), 'GET /api/meta': { body: META } });
    renderSystem();
    expect(await screen.findByText('thẻ tài khoản')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/account$/);
    expect(screen.queryByRole('link', { name: t('settings.tab.system') })).not.toBeInTheDocument();
  });

  it('drops the "saved" password hint once host or security differ from the loaded values', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({
      smtp: { source: 'settings', host: 'db.example.com', port: 587, security: 'starttls', username: 'u', from: 'a@example.com', password_status: 'saved' },
    }) } });
    renderSystem();
    const user = userEvent.setup();
    const host = await screen.findByLabelText(t('system.smtp.host'));
    expect(screen.getByText(t('system.smtp.password.saved'))).toBeInTheDocument();
    await user.type(host, 'x');
    expect(screen.queryByText(t('system.smtp.password.saved'))).not.toBeInTheDocument();
    expect(screen.getByText(t('system.smtp.password.needed'))).toBeInTheDocument();
    await user.type(host, '{Backspace}');
    expect(screen.getByText(t('system.smtp.password.saved'))).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(t('system.smtp.security')), 'ssl');
    expect(screen.queryByText(t('system.smtp.password.saved'))).not.toBeInTheDocument();
    expect(screen.getByText(t('system.smtp.password.needed'))).toBeInTheDocument();
  });

  it('shows a server invalid_smtp for the password under the password field', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM }, 'PUT /api/system/settings': fail(422, { code: 'invalid_smtp', field: 'password' }) });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.save') }));
    const message = await screen.findByText(t('system.smtp.invalidField'));
    expect(fieldGroup(screen.getByLabelText(t('system.smtp.password'))).contains(message)).toBe(true);
    expect(fieldGroup(screen.getByLabelText(t('system.smtp.from'))).contains(message)).toBe(false);
  });

  it('keeps unsaved SMTP edits (including the password) when the registration card is saved', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM },
      'PUT /api/system/settings': { body: systemWith({ registration_open: false }) } });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.type(screen.getByLabelText(t('system.smtp.password')), 'bi-mat');
    await user.click(regCard().getByRole('checkbox', { name: t('system.registration.open') }));
    await user.click(regCard().getByRole('button', { name: t('system.registration.save') }));
    expect(await screen.findByText(t('system.registration.saved'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('system.smtp.host'))).toHaveValue('smtp.example.com');
    expect(screen.getByLabelText(t('system.smtp.password'))).toHaveValue('bi-mat');
  });

  it('keeps an unsaved pending limit when the SMTP card is saved, and clears the typed password', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM },
      'PUT /api/system/settings': { body: systemWith({ smtp: { source: 'settings', host: 'smtp.example.com', password_status: 'saved' } }) } });
    renderSystem();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('system.limit.label')), '7');
    await user.type(screen.getByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.type(screen.getByLabelText(t('system.smtp.password')), 'bi-mat');
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.save') }));
    expect(await screen.findByText(t('system.smtp.saved'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('system.limit.label'))).toHaveValue(7);
    expect(screen.getByLabelText(t('system.smtp.password'))).toHaveValue('');
  });

  it('keeps focus on the security select across consecutive changes', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: SYSTEM } });
    renderSystem();
    const user = userEvent.setup();
    const select = await screen.findByLabelText(t('system.smtp.security'));
    select.focus({ preventScroll: true });
    await user.selectOptions(select, 'ssl');
    expect(screen.getByLabelText(t('system.smtp.security'))).toBe(select);
    await user.selectOptions(screen.getByLabelText(t('system.smtp.security')), 'none');
    expect(screen.getByLabelText(t('system.smtp.security'))).toBe(select);
    expect(select).toHaveValue('none');
  });

  it('shows the "needed" hint only while the password is empty, and compares the host case-insensitively', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({
      smtp: { source: 'settings', host: 'smtp.example.com', password_status: 'saved' } }) } });
    renderSystem();
    const user = userEvent.setup();
    const host = await screen.findByLabelText(t('system.smtp.host'));
    await user.clear(host);
    await user.type(host, 'SMTP.Example.COM');
    expect(screen.getByText(t('system.smtp.password.saved'))).toBeInTheDocument();
    await user.type(host, '2');
    expect(screen.getByText(t('system.smtp.password.needed'))).toBeInTheDocument();
    await user.type(screen.getByLabelText(t('system.smtp.password')), 'x');
    expect(screen.queryByText(t('system.smtp.password.needed'))).not.toBeInTheDocument();
  });

  it('falls back to a reload when clearing succeeded but the follow-up GET failed', async () => {
    mockApi({ ...AS_ADMIN,
      'GET /api/system/settings': sequence({ body: systemWith({ smtp: { source: 'settings', host: 'db.example.com' } }) }, fail(500, { code: 'unknown' }), { body: SYSTEM }),
      'DELETE /api/system/settings/smtp': { status: 204 } });
    renderSystem();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('system.smtp.title') });
    await user.click(smtpCard().getByRole('button', { name: t('system.smtp.clear') }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('system.smtp.clear') }));
    expect(await screen.findByText(t('system.smtp.source.none'))).toBeInTheDocument();
    expect(screen.queryByText(t('error.unknown'))).not.toBeInTheDocument();
  });

  it('does not blank the limit before "Đặt về mặc định" succeeds', async () => {
    mockApi({ ...AS_ADMIN, 'GET /api/system/settings': { body: systemWith({ max_pending_per_user: 7 }) },
      'PUT /api/system/settings': fail(500, { code: 'unknown' }) });
    renderSystem();
    const user = userEvent.setup();
    await screen.findByLabelText(t('system.limit.label'));
    await user.click(regCard().getByRole('button', { name: t('system.limit.reset') }));
    expect(await regCard().findByText(t('error.unknown'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('system.limit.label'))).toHaveValue(7);
  });
});
