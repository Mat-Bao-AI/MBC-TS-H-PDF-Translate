import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { GuestOnly, RequireAuth } from '../auth/RequireAuth';
import { t } from '../i18n/t';
import { instanceWith } from '../test/fixtures';
import { mockApi, type Handler } from '../test/mockApi';
import { renderApp } from '../test/render';
import { ConfirmEmailPage } from './ConfirmEmailPage';
import { ForgotPasswordPage } from './ForgotPasswordPage';
import { LoginPage } from './LoginPage';
import { RegisterPage } from './RegisterPage';
import { ResetPasswordPage } from './ResetPasswordPage';
import { VerifyEmailPage } from './VerifyEmailPage';

const ME = { id: 'u1', email: 'an@example.com', display_name: null };
const GUEST: Record<string, Handler> = { 'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated' } } } };
const fail = (status: number, code: string) => ({ status, body: { detail: { code } } });

function renderAuth(at: string) {
  return renderApp(
    <Routes>
      <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
      <Route path="/register" element={<GuestOnly><RegisterPage /></GuestOnly>} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/confirm-email" element={<ConfirmEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/files/:id" element={<RequireAuth><p>trang tệp</p></RequireAuth>} />
      <Route path="/" element={<RequireAuth><p>trang chính</p></RequireAuth>} />
    </Routes>,
    { at },
  );
}

async function fillLogin(email = 'an@example.com', password = 'mat-khau-8') {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(t('field.email')), email);
  await user.type(screen.getByLabelText(t('field.password')), password);
  await user.click(screen.getByRole('button', { name: t('login.submit') }));
  return user;
}

describe('LoginPage', () => {
  it('signs in and returns to the page the user wanted', async () => {
    const { calls } = mockApi({ ...GUEST, 'POST /api/auth/login': { body: ME } });
    renderAuth('/login?next=%2Ffiles%2Fabc');
    await fillLogin();
    expect(await screen.findByText('trang tệp')).toBeInTheDocument();
    const login = calls.find((call) => call.url === '/api/auth/login')!;
    expect(JSON.parse(String(login.body))).toEqual({ email: 'an@example.com', password: 'mat-khau-8' });
  });

  it('ignores an unsafe next and lands on the home page', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/login': { body: ME } });
    renderAuth('/login?next=%2F%2Fevil.com');
    await fillLogin();
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  });

  it('shows wrong credentials without leaving the page', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/login': fail(401, 'invalid_credentials') });
    renderAuth('/login');
    await fillLogin();
    expect(await screen.findByText(t('error.invalid_credentials'))).toBeInTheDocument();
  });

  it('offers to resend the verification email', async () => {
    const { calls } = mockApi({
      ...GUEST,
      'POST /api/auth/login': fail(403, 'email_unverified'),
      'POST /api/auth/resend-verification': { status: 202, body: { status: 'accepted' } },
    });
    renderAuth('/login');
    const user = await fillLogin();
    await user.click(await screen.findByRole('button', { name: t('login.resend') }));
    expect(await screen.findByText(t('login.resent'))).toBeInTheDocument();
    const resend = calls.find((call) => call.url === '/api/auth/resend-verification')!;
    expect(JSON.parse(String(resend.body))).toEqual({ email: 'an@example.com' });
  });

  it('says the account was deleted when coming from the danger zone', async () => {
    mockApi(GUEST);
    renderAuth('/login?deleted=1');
    expect(await screen.findByText(t('login.deleted'))).toBeInTheDocument();
  });

  it('shows an error instead of a false success when resend fails', async () => {
    mockApi({
      ...GUEST,
      'POST /api/auth/login': fail(403, 'email_unverified'),
      'POST /api/auth/resend-verification': { status: 500, body: {} },
    });
    renderAuth('/login');
    const user = await fillLogin();
    await user.click(await screen.findByRole('button', { name: t('login.resend') }));
    expect(await screen.findByText(t('error.unknown'))).toBeInTheDocument();
    expect(screen.queryByText(t('login.resent'))).not.toBeInTheDocument();
  });
});

describe('RegisterPage', () => {
  it('validates fields before calling the server', async () => {
    const { calls } = mockApi(GUEST);
    renderAuth('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'khong-phai-email');
    await user.type(screen.getByLabelText(t('field.password')), 'ngan');
    await user.click(screen.getByRole('button', { name: t('register.submit') }));
    expect(screen.getByText(t('error.invalid_email'))).toBeInTheDocument();
    expect(screen.getByText(t('error.invalid_password'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
  });

  it('tells the user to check their inbox', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/register': { status: 202, body: { status: 'accepted' } } });
    renderAuth('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.type(screen.getByLabelText(t('field.password')), 'mat-khau-8');
    await user.click(screen.getByRole('button', { name: t('register.submit') }));
    expect(await screen.findByText(t('register.doneTitle'))).toBeInTheDocument();
    expect(screen.getByText(t('register.doneBody', { email: 'an@example.com' }))).toBeInTheDocument();
  });

  it('puts server field errors under the field', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/register': fail(422, 'invalid_email') });
    renderAuth('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.type(screen.getByLabelText(t('field.password')), 'mat-khau-8');
    await user.click(screen.getByRole('button', { name: t('register.submit') }));
    expect(await screen.findByText(t('error.invalid_email'))).toBeInTheDocument();
  });
});

describe('VerifyEmailPage', () => {
  it('verifies, signs in and goes home', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/verify-email': { body: ME } });
    renderAuth('/verify-email?token=abc');
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
  });

  it('verifies without signing in when the link was opened in another browser', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/verify-email': { body: { status: 'verified' } } });
    renderAuth('/verify-email?token=abc');
    expect(await screen.findByText(t('verify.done'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('verify.login') })).toHaveAttribute('href', '/login');
    expect(screen.getByTestId('location')).toHaveTextContent('/verify-email?token=abc');
    expect(screen.queryByText('trang chính')).not.toBeInTheDocument();
  });

  it('goes to the login page from the verified message', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/verify-email': { body: { status: 'verified' } } });
    renderAuth('/verify-email?token=abc');
    await userEvent.setup().click(await screen.findByRole('link', { name: t('verify.login') }));
    expect(await screen.findByRole('button', { name: t('login.submit') })).toBeInTheDocument();
  });

  it('explains a dead link', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/verify-email': fail(400, 'invalid_token') });
    renderAuth('/verify-email?token=abc');
    expect(await screen.findByText(t('error.invalid_token'))).toBeInTheDocument();
  });

  it('explains a link without token', async () => {
    mockApi(GUEST);
    renderAuth('/verify-email');
    expect(await screen.findByText(t('verify.missing'))).toBeInTheDocument();
  });
});

describe('ForgotPasswordPage and ResetPasswordPage', () => {
  it('always confirms the reset request', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/forgot-password': { status: 202, body: { status: 'accepted' } } });
    renderAuth('/forgot-password');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.click(screen.getByRole('button', { name: t('forgot.submit') }));
    expect(await screen.findByText(t('forgot.done'))).toBeInTheDocument();
  });

  it('saves the new password', async () => {
    const { calls } = mockApi({ ...GUEST, 'POST /api/auth/reset-password': { status: 204 } });
    renderAuth('/reset-password?token=tok');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.newPassword')), 'mat-khau-moi');
    await user.click(screen.getByRole('button', { name: t('reset.submit') }));
    expect(await screen.findByText(t('reset.done'))).toBeInTheDocument();
    const reset = calls.find((call) => call.url === '/api/auth/reset-password')!;
    expect(JSON.parse(String(reset.body))).toEqual({ token: 'tok', password: 'mat-khau-moi' });
  });

  it('rejects a weak password locally and a dead token from the server', async () => {
    const { calls } = mockApi({ ...GUEST, 'POST /api/auth/reset-password': fail(400, 'invalid_token') });
    renderAuth('/reset-password?token=tok');
    const user = userEvent.setup();
    const field = await screen.findByLabelText(t('field.newPassword'));
    await user.type(field, 'ngan');
    await user.click(screen.getByRole('button', { name: t('reset.submit') }));
    expect(screen.getByText(t('error.invalid_password'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
    await user.clear(field);
    await user.type(field, 'mat-khau-moi');
    await user.click(screen.getByRole('button', { name: t('reset.submit') }));
    expect(await screen.findByText(t('error.invalid_token'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('reset.requestNew') })).toHaveAttribute('href', '/forgot-password');
  });
});

describe('ConfirmEmailPage', () => {
  it('confirms the new email without needing a session', async () => {
    const { calls } = mockApi({
      ...GUEST, 'POST /api/auth/confirm-email': { body: { ...ME, email: 'moi@example.com' } },
    });
    renderAuth('/confirm-email?token=abc');
    expect(await screen.findByText(t('confirmEmail.done', { email: 'moi@example.com' }))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('confirmEmail.toSettings') })).toHaveAttribute('href', '/settings/account');
    const confirm = calls.find((call) => call.url === '/api/auth/confirm-email')!;
    expect(JSON.parse(String(confirm.body))).toEqual({ token: 'abc' });
  });

  it('explains an address taken in the meantime and links back to login', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/confirm-email': fail(409, 'email_taken') });
    renderAuth('/confirm-email?token=abc');
    expect(await screen.findByText(t('error.email_taken'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('forgot.back') })).toHaveAttribute('href', '/login');
  });

  it('explains a dead link and a link without token', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/confirm-email': fail(400, 'invalid_token') });
    const { unmount } = renderAuth('/confirm-email?token=abc');
    expect(await screen.findByText(t('error.invalid_token'))).toBeInTheDocument();
    unmount();
    renderAuth('/confirm-email');
    expect(await screen.findByText(t('verify.missing'))).toBeInTheDocument();
  });
});

describe('registration_open / mail_enabled', () => {
  const CLOSED = { ...GUEST, 'GET /api/setup/status': instanceWith({ registration_open: false }) };
  const NO_MAIL = { ...GUEST, 'GET /api/setup/status': instanceWith({ mail_enabled: false }) };

  it('register shows the closed card instead of the form', async () => {
    mockApi(CLOSED);
    renderAuth('/register');
    expect(await screen.findByRole('heading', { name: t('register.closedTitle') })).toBeInTheDocument();
    expect(screen.getByText(t('register.closedBody'))).toBeInTheDocument();
    expect(screen.queryByLabelText(t('field.email'))).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('register.login') })).toHaveAttribute('href', '/login');
  });

  it('login hides the "Tạo tài khoản" link while registration is closed', async () => {
    mockApi(CLOSED);
    renderAuth('/login');
    await screen.findByLabelText(t('field.email'));
    expect(screen.queryByRole('link', { name: t('login.register') })).not.toBeInTheDocument();
  });

  it('register says the account is ready when the server has no mail', async () => {
    mockApi({ ...NO_MAIL, 'POST /api/auth/register': { status: 202, body: { status: 'accepted' } } });
    renderAuth('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.type(screen.getByLabelText(t('field.password')), 'mat-khau-8');
    await user.click(screen.getByRole('button', { name: t('register.submit') }));
    expect(await screen.findByRole('heading', { name: t('register.readyTitle') })).toBeInTheDocument();
    expect(screen.getByText(t('register.readyBody'))).toBeInTheDocument();
    expect(screen.queryByText(t('register.doneTitle'))).not.toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: t('register.readyLogin') }));
    expect(await screen.findByRole('button', { name: t('login.submit') })).toBeInTheDocument();
  });

  it('register shows a server-side closed or not-set-up answer', async () => {
    mockApi({ ...GUEST, 'POST /api/auth/register': fail(403, 'registration_closed') });
    renderAuth('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.type(screen.getByLabelText(t('field.password')), 'mat-khau-8');
    await user.click(screen.getByRole('button', { name: t('register.submit') }));
    expect(await screen.findByText(t('error.registration_closed'))).toBeInTheDocument();
  });

  it('forgot-password shows the no-mail message instead of the form', async () => {
    mockApi(NO_MAIL);
    renderAuth('/forgot-password');
    expect(await screen.findByText(t('mail.notConfigured'))).toBeInTheDocument();
    expect(screen.queryByLabelText(t('field.email'))).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('forgot.back') })).toBeInTheDocument();
  });

  it('login explains instead of offering resend when the server has no mail', async () => {
    mockApi({ ...NO_MAIL, 'POST /api/auth/login': fail(403, 'email_unverified') });
    renderAuth('/login');
    await fillLogin();
    expect(await screen.findByText(t('error.email_unverified'))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('login.resend') })).not.toBeInTheDocument();
    expect(screen.getByText(t('mail.notConfigured'))).toBeInTheDocument();
  });
});
