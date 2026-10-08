import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { GuestOnly, RequireAuth } from '../auth/RequireAuth';
import { t } from '../i18n/t';
import { ADMIN, INSTANCE, instanceWith } from '../test/fixtures';
import { mockApi, sequence, type Call, type Handler } from '../test/mockApi';
import { renderApp } from '../test/render';
import { SetupPage } from './SetupPage';

const UNAUTH = { status: 401, body: { detail: { code: 'unauthenticated' } } };
const NEEDS_SETUP: Record<string, Handler> = { 'GET /api/auth/me': UNAUTH, 'GET /api/setup/status': instanceWith({ needs_setup: true }) };
/** Sau bước 1: status nạp lại trả needs_setup=false. Dựng mới mỗi test: `sequence` giữ con trỏ. */
const setupFlow = (): Record<string, Handler> => ({
  'GET /api/auth/me': UNAUTH,
  'GET /api/setup/status': sequence({ body: { ...INSTANCE, needs_setup: true } }, { body: { ...INSTANCE, needs_setup: false } }),
  'POST /api/setup': { body: ADMIN },
});
const fail = (status: number, code: string) => ({ status, body: { detail: { code } } });

function renderSetup(at = '/setup') {
  return renderApp(
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<GuestOnly><p>trang đăng nhập</p></GuestOnly>} />
      <Route path="/" element={<RequireAuth><p>trang chính</p></RequireAuth>} />
    </Routes>,
    { at },
  );
}

async function fillStep1(password = 'mat-khau-8', confirm = password) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(t('field.email')), 'Chu@Example.com');
  await user.type(screen.getByLabelText(t('field.password')), password);
  await user.type(screen.getByLabelText(t('setup.confirmPassword')), confirm);
  return user;
}

const submitStep1 = (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: t('setup.submit') }));
const posted = (calls: Call[], url: string) => calls.filter((call) => call.method !== 'GET' && call.url === url);

describe('SetupPage', () => {
  it('shows step 1 with the display name, email and two password fields', async () => {
    mockApi(NEEDS_SETUP);
    renderSetup();
    expect(await screen.findByRole('heading', { name: t('setup.title1') })).toBeInTheDocument();
    expect(screen.getByText(t('setup.step1'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('setup.displayName'))).toBeInTheDocument();
    expect(screen.queryByLabelText(t('setup.token'))).not.toBeInTheDocument();
  });

  it('validates locally and does not call the API when the passwords differ', async () => {
    const { calls } = mockApi(NEEDS_SETUP);
    renderSetup();
    const user = await fillStep1('mat-khau-8', 'mat-khau-9');
    await submitStep1(user);
    expect(await screen.findByText(t('setup.password.mismatch'))).toBeInTheDocument();
    expect(posted(calls, '/api/setup')).toHaveLength(0);
  });

  it('asks for the setup token only when the server requires it', async () => {
    mockApi({ ...NEEDS_SETUP, 'GET /api/setup/status': instanceWith({ needs_setup: true, setup_token_required: true }) });
    renderSetup();
    expect(await screen.findByLabelText(t('setup.token'))).toBeInTheDocument();
    expect(screen.getByText(t('setup.token.hint'))).toBeInTheDocument();
  });

  it('creates the admin, signs in and moves to step 2 without changing the route', async () => {
    const { calls } = mockApi(setupFlow());
    renderSetup();
    const user = await fillStep1();
    await user.type(screen.getByLabelText(t('setup.displayName')), 'Quản trị');
    await submitStep1(user);
    expect(await screen.findByRole('heading', { name: t('setup.title2') })).toBeInTheDocument();
    expect(screen.getByText(t('setup.step2'))).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/setup$/);
    expect(JSON.parse(String(posted(calls, '/api/setup')[0].body))).toEqual({ display_name: 'Quản trị', email: 'Chu@Example.com', password: 'mat-khau-8' });
    expect(calls.filter((call) => call.url === '/api/setup/status')).toHaveLength(2); // nạp lại sau bước 1
    expect(screen.getByLabelText(t('system.smtp.host'))).toBeInTheDocument();
  });

  it('puts a wrong setup token under the token field and sends it when required', async () => {
    const { calls } = mockApi({ ...NEEDS_SETUP, 'GET /api/setup/status': instanceWith({ needs_setup: true, setup_token_required: true }),
      'POST /api/setup': fail(403, 'invalid_setup_token') });
    renderSetup();
    const user = await fillStep1();
    await user.type(screen.getByLabelText(t('setup.token')), 'sai');
    await submitStep1(user);
    expect(await screen.findByText(t('error.invalid_setup_token'))).toBeInTheDocument();
    expect(JSON.parse(String(posted(calls, '/api/setup')[0].body)).setup_token).toBe('sai');
    expect(screen.getByRole('heading', { name: t('setup.title1') })).toBeInTheDocument();
  });

  it('sends a test mail from the unsaved SMTP values in step 2', async () => {
    const { calls } = mockApi({ ...setupFlow(), 'POST /api/system/smtp/test': { body: { sent_to: 'chu@example.com' } } });
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.type(screen.getByLabelText(t('system.smtp.from')), 'no-reply@example.com');
    await user.click(screen.getByRole('button', { name: t('system.smtp.test') }));
    expect(await screen.findByText(t('system.smtp.testOk', { email: 'chu@example.com' }))).toBeInTheDocument();
    expect(JSON.parse(String(posted(calls, '/api/system/smtp/test')[0].body))).toEqual({
      smtp: { host: 'smtp.example.com', port: 587, security: 'starttls', username: '', from: 'no-reply@example.com' } });
    expect(posted(calls, '/api/system/settings')).toHaveLength(0);
  });

  it('skip goes home without saving anything', async () => {
    const { calls } = mockApi(setupFlow());
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    await user.click(await screen.findByRole('button', { name: t('setup.skip') }));
    expect(await screen.findByText('trang chính')).toBeInTheDocument(); // đã đăng nhập từ bước 1
    expect(posted(calls, '/api/system/settings')).toHaveLength(0);
  });

  it('finish saves the SMTP and goes home', async () => {
    const { calls } = mockApi({ ...setupFlow(), 'PUT /api/system/settings': { body: {} } });
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.type(screen.getByLabelText(t('system.smtp.from')), 'no-reply@example.com');
    await user.click(screen.getByRole('button', { name: t('setup.finish') }));
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
    expect(JSON.parse(String(posted(calls, '/api/system/settings')[0].body))).toEqual({
      smtp: { host: 'smtp.example.com', port: 587, security: 'starttls', username: '', from: 'no-reply@example.com' } });
  });

  it('leaves /setup when the instance no longer needs setup', async () => {
    mockApi({ 'GET /api/auth/me': UNAUTH, 'GET /api/setup/status': instanceWith({ needs_setup: false }) });
    renderSetup();
    expect(await screen.findByText('trang đăng nhập')).toBeInTheDocument(); // / → RequireAuth → /login
  });

  it('trims the setup token before sending it', async () => {
    const { calls } = mockApi({ ...NEEDS_SETUP, 'GET /api/setup/status': instanceWith({ needs_setup: true, setup_token_required: true }),
      'POST /api/setup': fail(403, 'invalid_setup_token') });
    renderSetup();
    const user = await fillStep1();
    await user.type(screen.getByLabelText(t('setup.token')), ' sai ');
    await submitStep1(user);
    await screen.findByText(t('error.invalid_setup_token'));
    expect(JSON.parse(String(posted(calls, '/api/setup')[0].body)).setup_token).toBe('sai');
  });

  it('step 2 does not show the "saved" password hint', async () => {
    mockApi(setupFlow());
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    await screen.findByLabelText(t('system.smtp.host'));
    expect(screen.queryByText(t('system.smtp.password.saved'))).not.toBeInTheDocument();
  });

  it('on setup_done it reloads the status and ends up at sign-in instead of staying on step 1', async () => {
    const { calls } = mockApi({
      'GET /api/auth/me': UNAUTH,
      'GET /api/setup/status': sequence({ body: { ...INSTANCE, needs_setup: true } }, { body: { ...INSTANCE, needs_setup: false } }),
      'POST /api/setup': fail(409, 'setup_done'),
    });
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    expect(await screen.findByText('trang đăng nhập')).toBeInTheDocument();
    expect(calls.filter((call) => call.url === '/api/setup/status')).toHaveLength(2);
  });
});

/**
 * Status: lần 1 (tải trang) và 2 (sau bước 1) báo needs_setup=true; lần 3 (lượt đợi của Bỏ qua / Hoàn tất) bị giữ tới
 * khi `release()` rồi báo false. Không đợi thì `/` thấy needs_setup=true và RequireAuth đẩy ngược về /setup.
 */
function slowThirdStatus(extra: Record<string, Handler> = {}) {
  const { fetchMock, calls } = mockApi({
    'GET /api/auth/me': UNAUTH,
    'GET /api/setup/status': sequence({ body: { ...INSTANCE, needs_setup: true } }, { body: { ...INSTANCE, needs_setup: true } },
      { body: { ...INSTANCE, needs_setup: false } }),
    'POST /api/setup': { body: ADMIN },
    ...extra,
  });
  const inner = fetchMock.getMockImplementation()!;
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let statusCalls = 0;
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    if (url === '/api/setup/status' && ++statusCalls === 3) {
      const reply = await inner(input, init);
      await gate;
      return reply;
    }
    return inner(input, init);
  });
  return { calls, release: () => act(async () => { release(); await gate; }) };
}

describe('SetupPage — step 2 waits for the slow status refresh', () => {
  it('skip stays on step 2 until the refresh answers, then goes home without bouncing back', async () => {
    const { release } = slowThirdStatus();
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    await user.click(await screen.findByRole('button', { name: t('setup.skip') }));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/setup$/);
    expect(screen.getByRole('heading', { name: t('setup.title2') })).toBeInTheDocument();
    expect(screen.queryByText('trang chính')).not.toBeInTheDocument();
    await release();
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: t('setup.title1') })).not.toBeInTheDocument();
  });

  it('finish saves, waits for the refresh, then goes home without bouncing back', async () => {
    const { release } = slowThirdStatus({ 'PUT /api/system/settings': { body: {} } });
    renderSetup();
    const user = await fillStep1();
    await submitStep1(user);
    await user.type(await screen.findByLabelText(t('system.smtp.host')), 'smtp.example.com');
    await user.type(screen.getByLabelText(t('system.smtp.from')), 'no-reply@example.com');
    await user.click(screen.getByRole('button', { name: t('setup.finish') }));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/setup$/);
    expect(screen.getByRole('heading', { name: t('setup.title2') })).toBeInTheDocument();
    expect(screen.queryByText('trang chính')).not.toBeInTheDocument();
    await release();
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
  });
});
