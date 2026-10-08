import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GuestOnly, RequireAuth } from '../../auth/RequireAuth';
import { AppShell } from '../../components/AppShell';
import { resetMetaCache } from '../../files/useMeta';
import { t } from '../../i18n/t';
import { ADMIN, ME, META, SIGNED_IN, instanceWith, signedInAs } from '../../test/fixtures';
import { mockApi, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { LoginPage } from '../LoginPage';
import { AccountSettingsPage } from './AccountSettingsPage';
import { SettingsLayout } from './SettingsLayout';

const BASE: Record<string, Handler> = { 'GET /api/meta': { body: META } };
const fail = (status: number, code: string) => ({ status, body: { detail: { code } } });

function renderAccount() {
  return renderApp(
    <Routes>
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="account" element={<AccountSettingsPage />} />
        </Route>
      </Route>
      <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
    </Routes>,
    { at: '/settings/account' },
  );
}

const card = (title: string) => within(screen.getByRole('region', { name: title }));
const bodyOf = (calls: { url: string; body: unknown }[], url: string) =>
  JSON.parse(String(calls.find((call) => call.url === url)!.body));

beforeEach(() => resetMetaCache());

describe('AccountSettingsPage — tên hiển thị', () => {
  it('saves the display name and updates the avatar at once', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, ...BASE,
      'PUT /api/account/profile': { body: { ...ME, display_name: 'Cường' } },
    });
    renderAccount();
    const user = userEvent.setup();
    const name = await screen.findByRole('textbox', { name: t('account.name.label') });
    expect(screen.getByRole('button', { name: t('shell.accountMenu') })).toHaveTextContent('A');
    await user.type(name, '  Cường ');
    await user.click(card(t('account.name.title')).getByRole('button', { name: t('account.name.submit') }));
    expect(await screen.findByText(t('account.name.saved'))).toBeInTheDocument();
    expect(bodyOf(calls, '/api/account/profile')).toEqual({ display_name: '  Cường ' });
    expect(name).toHaveValue('Cường');
    expect(screen.getByRole('button', { name: t('shell.accountMenu') })).toHaveTextContent('C');
  });

  it('starts from the saved name and shows a server error under the field', async () => {
    mockApi({
      ...signedInAs({ display_name: 'An' }), ...BASE,
      'PUT /api/account/profile': fail(422, 'invalid_display_name'),
    });
    renderAccount();
    const user = userEvent.setup();
    const name = await screen.findByRole('textbox', { name: t('account.name.label') });
    expect(name).toHaveValue('An');
    expect(name).toHaveAttribute('maxlength', '50');
    await user.click(card(t('account.name.title')).getByRole('button', { name: t('account.name.submit') }));
    expect(await screen.findByText(t('error.invalid_display_name'))).toBeInTheDocument();
    expect(screen.queryByText(t('account.name.saved'))).not.toBeInTheDocument();
  });
});

describe('AccountSettingsPage — đổi email', () => {
  it('sends a confirmation link and says the email changes only after the click', async () => {
    const { calls } = mockApi({
      ...SIGNED_IN, ...BASE,
      'POST /api/account/email': { status: 202, body: { status: 'accepted' } },
    });
    renderAccount();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('account.email.title') });
    const emailCard = card(t('account.email.title'));
    await user.type(emailCard.getByLabelText(t('account.email.label')), 'moi@example.com');
    await user.type(emailCard.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.click(emailCard.getByRole('button', { name: t('account.email.submit') }));
    expect(await screen.findByText(t('account.email.sent', { email: 'moi@example.com' }))).toBeInTheDocument();
    expect(bodyOf(calls, '/api/account/email')).toEqual({ new_email: 'moi@example.com', password: 'mat-khau-8' });
    expect(emailCard.getByLabelText(t('field.currentPassword'))).toHaveValue('');
  });

  it('checks the address locally and puts a wrong password under its field', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/email': fail(400, 'wrong_password') });
    renderAccount();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('account.email.title') });
    const emailCard = card(t('account.email.title'));
    await user.type(emailCard.getByLabelText(t('account.email.label')), 'khong-phai-email');
    await user.click(emailCard.getByRole('button', { name: t('account.email.submit') }));
    expect(emailCard.getByText(t('error.invalid_email'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
    await user.clear(emailCard.getByLabelText(t('account.email.label')));
    await user.type(emailCard.getByLabelText(t('account.email.label')), 'moi@example.com');
    await user.type(emailCard.getByLabelText(t('field.currentPassword')), 'sai-mat-khau');
    await user.click(emailCard.getByRole('button', { name: t('account.email.submit') }));
    expect(await emailCard.findByText(t('error.wrong_password'))).toBeInTheDocument();
  });
});

describe('AccountSettingsPage — đổi email khi không có thư', () => {
  it('tells a non-admin that mail is not configured, with no link and no "contact the admin"', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/setup/status': instanceWith({ mail_enabled: false }), ...BASE });
    renderAccount();
    const emailCard = within(await screen.findByRole('region', { name: t('account.email.title') }));
    expect(emailCard.getByText(t('account.email.noMail'))).toBeInTheDocument();
    expect(emailCard.queryByText(/quản trị viên/)).not.toBeInTheDocument();
    expect(emailCard.queryByLabelText(t('account.email.label'))).not.toBeInTheDocument();
    expect(emailCard.queryByRole('link')).not.toBeInTheDocument();
    expect(emailCard.queryByRole('button')).not.toBeInTheDocument();
  });

  it('gives an admin a link to the SMTP settings that navigates client-side', async () => {
    mockApi({ ...signedInAs(ADMIN), 'GET /api/setup/status': instanceWith({ mail_enabled: false }), ...BASE });
    renderAccount();
    const emailCard = within(await screen.findByRole('region', { name: t('account.email.title') }));
    expect(emailCard.getByText(t('account.email.noMail'))).toBeInTheDocument();
    const link = emailCard.getByRole('link', { name: t('account.email.configureSmtp') });
    expect(link).toHaveAttribute('href', '/settings/system');
    await userEvent.setup().click(link);
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/system$/);
  });
});

describe('AccountSettingsPage — đổi mật khẩu', () => {
  it('refuses a mismatched repeat without calling the server', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, ...BASE });
    renderAccount();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('account.password.title') });
    const passwordCard = card(t('account.password.title'));
    await user.type(passwordCard.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.type(passwordCard.getByLabelText(t('field.newPassword')), 'mat-khau-moi-9');
    await user.type(passwordCard.getByLabelText(t('field.confirmPassword')), 'mat-khau-moi-0');
    await user.click(passwordCard.getByRole('button', { name: t('account.password.submit') }));
    expect(passwordCard.getByText(t('account.password.mismatch'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
  });

  it('changes the password and clears the form', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/password': { status: 204 } });
    renderAccount();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('account.password.title') });
    const passwordCard = card(t('account.password.title'));
    await user.type(passwordCard.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.type(passwordCard.getByLabelText(t('field.newPassword')), 'mat-khau-moi-9');
    await user.type(passwordCard.getByLabelText(t('field.confirmPassword')), 'mat-khau-moi-9');
    await user.click(passwordCard.getByRole('button', { name: t('account.password.submit') }));
    expect(await screen.findByText(t('account.password.done'))).toBeInTheDocument();
    expect(bodyOf(calls, '/api/account/password')).toEqual({ current_password: 'mat-khau-8', new_password: 'mat-khau-moi-9' });
    expect(passwordCard.getByLabelText(t('field.newPassword'))).toHaveValue('');
  });

  it('puts a wrong current password under its field', async () => {
    mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/password': fail(400, 'wrong_password') });
    renderAccount();
    const user = userEvent.setup();
    await screen.findByRole('region', { name: t('account.password.title') });
    const passwordCard = card(t('account.password.title'));
    await user.type(passwordCard.getByLabelText(t('field.currentPassword')), 'sai-mat-khau');
    await user.type(passwordCard.getByLabelText(t('field.newPassword')), 'mat-khau-moi-9');
    await user.type(passwordCard.getByLabelText(t('field.confirmPassword')), 'mat-khau-moi-9');
    await user.click(passwordCard.getByRole('button', { name: t('account.password.submit') }));
    expect(await passwordCard.findByText(t('error.wrong_password'))).toBeInTheDocument();
    expect(screen.queryByText(t('account.password.done'))).not.toBeInTheDocument();
  });
});

describe('AccountSettingsPage — vùng nguy hiểm', () => {
  async function openDeleteDialog(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByRole('region', { name: t('account.danger.title') });
    await user.click(card(t('account.danger.title')).getByRole('button', { name: t('account.danger.open') }));
    return within(await screen.findByRole('dialog'));
  }

  it('draws the danger card with a solid red border and the others with the plain one', async () => {
    // jsdom's CSSOM drops `border` shorthands, so read the rules emotion hands to insertRule instead.
    const inserted: string[] = [];
    const original = CSSStyleSheet.prototype.insertRule;
    const spy = vi.spyOn(CSSStyleSheet.prototype, 'insertRule').mockImplementation(function (this: CSSStyleSheet, rule, index) {
      inserted.push(rule);
      return original.call(this, rule, index);
    });
    mockApi({ ...SIGNED_IN, ...BASE });
    renderAccount();
    await screen.findByRole('region', { name: t('account.danger.title') });
    spy.mockRestore();
    const cards = inserted.filter((rule) => rule.includes('DynamicCardWrapper'));
    expect(cards.filter((rule) => /border:1px solid[^;]*;border-color:var\(--color-feedback-error\)/.test(rule))).toHaveLength(1);
    expect(cards.filter((rule) => /border:1px solid/.test(rule))).toHaveLength(2); // + the card with the default colour
  });

  it('deletes the account and lands on the login page with a notice', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/delete': { status: 204 } });
    renderAccount();
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    await user.type(dialog.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.click(dialog.getByRole('button', { name: t('account.danger.confirm') }));
    expect(await screen.findByText(t('login.deleted'))).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login?deleted=1');
    expect(bodyOf(calls, '/api/account/delete')).toEqual({ password: 'mat-khau-8' });
    expect(calls.some((call) => call.url === '/api/auth/logout')).toBe(false); // server đã huỷ phiên
  });

  it('sends only one delete request when the confirm button is double-clicked', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/delete': { status: 204 } });
    renderAccount();
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    await user.type(dialog.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.dblClick(dialog.getByRole('button', { name: t('account.danger.confirm') }));
    expect(await screen.findByText(t('login.deleted'))).toBeInTheDocument();
    expect(calls.filter((call) => call.url === '/api/account/delete')).toHaveLength(1);
  });

  it('keeps the dialog open with the error when the password is wrong', async () => {
    mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/delete': fail(400, 'wrong_password') });
    renderAccount();
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    await user.type(dialog.getByLabelText(t('field.currentPassword')), 'sai-mat-khau');
    await user.click(dialog.getByRole('button', { name: t('account.danger.confirm') }));
    expect(await dialog.findByText(t('error.wrong_password'))).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/settings/account');
  });

  it('explains that a running file blocks the deletion, and cancel closes the dialog', async () => {
    mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/account/delete': fail(409, 'file_running') });
    renderAccount();
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    await user.type(dialog.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.click(dialog.getByRole('button', { name: t('account.danger.confirm') }));
    expect(await dialog.findByText(`${t('error.file_running')} ${t('account.danger.fileRunning')}`)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: t('common.cancel') }));
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
