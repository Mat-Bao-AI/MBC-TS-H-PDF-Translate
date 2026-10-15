import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from '../../App';
import { resetMetaCache } from '../../files/useMeta';
import { t } from '../../i18n/t';
import { ADMIN, META, SETTINGS, SIGNED_IN, SYSTEM, settingsWith, signedInAs } from '../../test/fixtures';
import { mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';

const BASE = { ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } };
const tabs = () => within(screen.getByRole('navigation', { name: t('settings.tabs') }));

beforeEach(() => resetMetaCache());

describe('SettingsLayout', () => {
  it('sends /settings to the account tab and marks it as the current one', async () => {
    mockApi(BASE);
    renderApp(<App />, { at: '/settings' });
    expect(await screen.findByText(t('account.signedInAs', { email: 'an@example.com' }))).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/account$/);
    expect(screen.getByRole('heading', { level: 1, name: t('settings.title') })).toBeInTheDocument();
    expect(tabs().getByRole('link', { name: t('settings.tab.account') })).toHaveAttribute('aria-current', 'page');
    expect(tabs().getByRole('link', { name: t('settings.tab.translation') })).not.toHaveAttribute('aria-current');
    expect(tabs().getAllByRole('link')).toHaveLength(2);
  });

  it('shows the Hệ thống tab only to an admin', async () => {
    mockApi({ ...BASE, ...signedInAs(ADMIN), 'GET /api/system/settings': { body: SYSTEM } });
    renderApp(<App />, { at: '/settings/system' });
    expect(await screen.findByRole('heading', { name: t('system.smtp.title') })).toBeInTheDocument();
    expect(tabs().getByRole('link', { name: t('settings.tab.system') })).toHaveAttribute('aria-current', 'page');
    expect(tabs().getAllByRole('link')).toHaveLength(3);
  });

  it('sends an unknown settings path to the account tab instead of an empty pane', async () => {
    mockApi(BASE);
    renderApp(<App />, { at: '/settings/khong-co' });
    expect(await screen.findByText(t('account.signedInAs', { email: 'an@example.com' }))).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/account$/);
    expect(tabs().getByRole('link', { name: t('settings.tab.account') })).toHaveAttribute('aria-current', 'page');
  });

  it('opens another tab without reloading the page', async () => {
    const { fetchMock } = mockApi(BASE);
    renderApp(<App />, { at: '/settings/account' });
    await screen.findByRole('navigation', { name: t('settings.tabs') });
    const meCalls = () => fetchMock.mock.calls.filter(([url]) => url === '/api/auth/me').length;
    const before = meCalls();
    await userEvent.setup().click(tabs().getByRole('link', { name: t('settings.tab.translation') }));
    expect(await screen.findByRole('heading', { name: t('settings.mode.title') })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/translation$/);
    expect(tabs().getByRole('link', { name: t('settings.tab.translation') })).toHaveAttribute('aria-current', 'page');
    expect(tabs().getByRole('link', { name: t('settings.tab.account') })).toHaveAttribute('href', '/settings/account');
    expect(meCalls()).toBe(before); // AuthProvider không gọi lại /api/auth/me: không có lượt tải lại trang
  });

  it('shows the Hồ sơ dịch tab only when advanced mode is on', async () => {
    mockApi({ ...BASE, ...signedInAs({ advance_mode: true }), 'GET /api/settings': { body: settingsWith({ advance_mode: true }) } });
    renderApp(<App />, { at: '/settings/profiles' });
    expect(await screen.findByRole('heading', { name: t('profiles.title.mine') })).toBeInTheDocument();
    expect(tabs().getByRole('link', { name: t('settings.tab.profiles') })).toHaveAttribute('aria-current', 'page');
    expect(tabs().getAllByRole('link')).toHaveLength(3);
  });

  it('sends /settings/profiles back to the translation tab when advanced mode is off', async () => {
    mockApi(BASE);
    renderApp(<App />, { at: '/settings/profiles' });
    expect(await screen.findByRole('heading', { name: t('settings.mode.title') })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/translation$/);
    expect(tabs().queryByRole('link', { name: t('settings.tab.profiles') })).not.toBeInTheDocument();
  });
});
