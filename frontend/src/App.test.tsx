import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from './App';
import { resetMetaCache } from './files/useMeta';
import { t } from './i18n/t';
import { ADMIN, GUEST, INSTANCE, META, SIGNED_IN, filePage, instanceWith } from './test/fixtures';
import { mockApi, sequence } from './test/mockApi';
import { renderApp } from './test/render';

beforeEach(() => resetMetaCache());

describe('App', () => {
  it('sends guests to the login page', async () => {
    mockApi({ 'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated' } } } });
    renderApp(<App />, { at: '/' });
    expect(await screen.findByRole('heading', { name: t('login.title') })).toBeInTheDocument();
  });

  it('sends unknown paths home for a signed-in user', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': { body: filePage([]) } });
    renderApp(<App />, { at: '/khong-co' });
    expect(await screen.findByRole('heading', { name: t('home.greeting', { name: 'an' }) })).toBeInTheDocument();
  });

  it('sends public pages to /setup while the instance needs setup', async () => {
    mockApi({ 'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated' } } }, 'GET /api/setup/status': instanceWith({ needs_setup: true }) });
    renderApp(<App />, { at: '/forgot-password' });
    expect(await screen.findByRole('heading', { name: t('setup.title1') })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/setup$/);
  });

  it('sends /setup home once the instance is set up', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': { body: filePage([]) } });
    renderApp(<App />, { at: '/setup' });
    expect(await screen.findByRole('heading', { name: t('home.greeting', { name: 'an' }) })).toBeInTheDocument();
  });
});

/** Trạng thái instance đổi dưới chân client (spec 2026-10-05): lần nạp đầu cũ, lần nạp lại báo trạng thái mới. */
const statusThen = (next: Partial<typeof INSTANCE>) => sequence({ body: INSTANCE }, { body: { ...INSTANCE, ...next } });
const fail = (status: number, code: string) => ({ status, body: { detail: { code } } });

describe('App — instance status follows the server', () => {
  it('reloads it after the last account is deleted, so /setup opens without a page reload', async () => {
    mockApi({ 'GET /api/auth/me': { body: ADMIN }, 'GET /api/meta': { body: META },
      'GET /api/setup/status': statusThen({ needs_setup: true }), 'POST /api/account/delete': { status: 204 } });
    renderApp(<App />, { at: '/settings/account' });
    const user = userEvent.setup();
    const danger = within(await screen.findByRole('region', { name: t('account.danger.title') }));
    await user.click(danger.getByRole('button', { name: t('account.danger.open') }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.type(dialog.getByLabelText(t('field.currentPassword')), 'mat-khau-8');
    await user.click(dialog.getByRole('button', { name: t('account.danger.confirm') }));
    expect(await screen.findByRole('heading', { name: t('setup.title1') })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/setup$/);
  });

  it('goes to /setup when sign-in answers setup_required', async () => {
    mockApi({ ...GUEST, 'GET /api/setup/status': statusThen({ needs_setup: true }), 'POST /api/auth/login': fail(409, 'setup_required') });
    renderApp(<App />, { at: '/login' });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.type(screen.getByLabelText(t('field.password')), 'mat-khau-8');
    await user.click(screen.getByRole('button', { name: t('login.submit') }));
    expect(await screen.findByRole('heading', { name: t('setup.title1') })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/setup$/);
  });

  it('shows the closed card when register answers registration_closed', async () => {
    mockApi({ ...GUEST, 'GET /api/setup/status': statusThen({ registration_open: false }),
      'POST /api/auth/register': fail(403, 'registration_closed') });
    renderApp(<App />, { at: '/register' });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.type(screen.getByLabelText(t('field.password')), 'mat-khau-8');
    await user.click(screen.getByRole('button', { name: t('register.submit') }));
    expect(await screen.findByRole('heading', { name: t('register.closedTitle') })).toBeInTheDocument();
    expect(screen.queryByLabelText(t('field.email'))).not.toBeInTheDocument();
  });

  it('swaps the forgot-password form for the no-mail message on mail_not_configured', async () => {
    mockApi({ ...GUEST, 'GET /api/setup/status': statusThen({ mail_enabled: false }),
      'POST /api/auth/forgot-password': fail(409, 'mail_not_configured') });
    renderApp(<App />, { at: '/forgot-password' });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(t('field.email')), 'an@example.com');
    await user.click(screen.getByRole('button', { name: t('forgot.submit') }));
    expect(await screen.findByText(t('mail.notConfigured'))).toBeInTheDocument();
    expect(screen.queryByLabelText(t('field.email'))).not.toBeInTheDocument();
  });
});
