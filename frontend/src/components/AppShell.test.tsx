import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAuth } from '../auth/RequireAuth';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { ADMIN, META, SIGNED_IN, filePage, instanceWith, signedInAs } from '../test/fixtures';
import { mockApi } from '../test/mockApi';
import { renderApp } from '../test/render';
import { AppShell } from './AppShell';

const BASE = { 'GET /api/meta': { body: META }, 'GET /api/files': { body: filePage([]) } };

function renderShell(at = '/') {
  return renderApp(
    <Routes>
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/" element={<><p>trang chính</p><input aria-label="ô ngoài menu" /></>} />
        <Route path="/settings/account" element={<p>cài đặt tài khoản</p>} />
        <Route path="/settings/translation" element={<p>cài đặt dịch thuật</p>} />
        <Route path="/settings/system" element={<p>cài đặt hệ thống</p>} />
      </Route>
      <Route path="/login" element={<p>trang đăng nhập</p>} />
    </Routes>,
    { at },
  );
}

const avatar = () => screen.findByRole('button', { name: t('shell.accountMenu') });

beforeEach(() => resetMetaCache());

describe('AccountMenu', () => {
  it('shows the first letter of the display name', async () => {
    mockApi({ ...signedInAs({ display_name: 'cường nguyễn' }), ...BASE });
    renderShell();
    expect(await avatar()).toHaveTextContent('C');
  });

  it('falls back to the part of the email before @', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    expect(await avatar()).toHaveTextContent('A');
  });

  it('opens the menu and closes it with Escape, returning focus to the avatar', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    const button = await avatar();
    expect(button).toHaveAttribute('aria-haspopup', 'menu');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await user.click(button);
    const menu = await screen.findByRole('menu');
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(menu).getByRole('menuitem', { name: t('shell.account') })).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: t('shell.translationSettings') })).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: t('shell.logout') })).toBeInTheDocument();
    expect(within(menu).queryByRole('menuitem', { name: t('shell.system') })).not.toBeInTheDocument();
    expect(screen.getByText('an@example.com')).toBeInTheDocument(); // dòng đầu: tên + email, không bấm được
    await user.keyboard('{Escape}');
    await vi.waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows the name and email in a left header, and an aria-hidden icon on every item', async () => {
    mockApi({ ...signedInAs({ display_name: 'An Nguyễn' }), ...BASE });
    renderShell();
    const user = userEvent.setup();
    await user.click(await avatar());
    const menu = await screen.findByRole('menu');
    const header = screen.getByTestId('account-menu-header');
    expect(within(header).getByText('An Nguyễn')).toBeInTheDocument();
    expect(within(header).getByText('an@example.com')).toBeInTheDocument();
    expect(within(header).getByText('A')).toBeInTheDocument(); // avatar nhỏ cùng chữ cái đầu
    expect(menu).not.toContainElement(header); // header không phải mục menu
    for (const item of within(menu).getAllByRole('menuitem')) {
      expect(item.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it('has no gear button in the top bar: the menu is the only way into settings', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    await avatar();
    expect(screen.queryByRole('link', { name: 'Cài đặt' })).not.toBeInTheDocument();
  });

  it('returns focus to the avatar without scrolling', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    const button = await avatar();
    await user.click(button);
    await screen.findByRole('menu');
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    await user.keyboard('{Escape}');
    await vi.waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(focus.mock.contexts).toContain(button);
    const call = focus.mock.calls[focus.mock.contexts.indexOf(button)];
    expect(call[0]).toEqual({ preventScroll: true });
    focus.mockRestore();
  });

  it('does not move focus when the page scrolls while the menu is closed', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    await avatar();
    await user.click(screen.getByText('trang chính'));
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    window.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('resize'));
    await user.click(screen.getByText('trang chính'));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument(); // Popover không được dựng khi đóng
    expect(focus).not.toHaveBeenCalled();
    focus.mockRestore();
  });

  it('closes on an outside click without moving focus back to the avatar', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    const button = await avatar();
    await user.click(button);
    await screen.findByRole('menu');
    await user.click(screen.getByRole('textbox', { name: 'ô ngoài menu' }));
    await vi.waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(screen.getByRole('textbox', { name: 'ô ngoài menu' })).toHaveFocus();
    expect(button).not.toHaveFocus();
  });

  it('closes on Tab and lets focus move on naturally', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    const button = await avatar();
    await user.click(button);
    await screen.findByRole('menu');
    // keydown thô (không chạy hành động mặc định của user-event): ngay sau đó focus phải ở avatar,
    // rồi trình duyệt tự đi tiếp từ avatar.
    fireEvent.keyDown(within(screen.getByRole('menu')).getAllByRole('menuitem')[0], { key: 'Tab' });
    await vi.waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(button).toHaveFocus();
  });

  it('closes the menu when clicking outside', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    await user.click(await avatar());
    await screen.findByRole('menu');
    await user.click(screen.getByText('trang chính'));
    await vi.waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });

  it('moves between items with the arrow keys and opens the chosen page with Enter', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    await user.click(await avatar());
    const items = within(await screen.findByRole('menu')).getAllByRole('menuitem');
    await vi.waitFor(() => expect(items[0]).toHaveFocus()); // mở menu: mục đầu nhận focus
    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{ArrowDown}{Enter}'); // mục 2: Cài đặt dịch thuật
    expect(await screen.findByText('cài đặt dịch thuật')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/settings/translation');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('opens the account settings from the menu', async () => {
    mockApi({ ...SIGNED_IN, ...BASE });
    renderShell();
    const user = userEvent.setup();
    await user.click(await avatar());
    await user.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: t('shell.account') }));
    expect(await screen.findByText('cài đặt tài khoản')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/settings/account');
  });

  it('signs out from the menu', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, ...BASE, 'POST /api/auth/logout': { status: 204 } });
    renderShell();
    const user = userEvent.setup();
    await user.click(await avatar());
    await user.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: t('shell.logout') }));
    expect(await screen.findByText('trang đăng nhập')).toBeInTheDocument();
    expect(calls.some((call) => call.url === '/api/auth/logout')).toBe(true);
  });
});

describe('AppShell — banner SMTP cho admin', () => {
  it('shows the no-SMTP banner to an admin and takes them to Hệ thống', async () => {
    mockApi({ ...signedInAs(ADMIN), 'GET /api/setup/status': instanceWith({ mail_enabled: false }), ...BASE });
    renderShell();
    expect(await screen.findByText(t('shell.smtpBanner'))).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: t('shell.smtpBanner.cta') }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/system$/);
  });

  it('closes the banner with the × at once, tells the server once and keeps it closed', async () => {
    const { calls } = mockApi({ ...signedInAs(ADMIN), 'GET /api/setup/status': instanceWith({ mail_enabled: false }),
      'POST /api/account/notices/smtp/dismiss': { status: 204 }, ...BASE });
    renderShell();
    await screen.findByText(t('shell.smtpBanner'));
    await userEvent.setup().click(screen.getByRole('button', { name: t('shell.smtpBanner.close') }));
    expect(screen.queryByText(t('shell.smtpBanner'))).not.toBeInTheDocument();
    await vi.waitFor(() => expect(calls.filter((call) => call.url === '/api/account/notices/smtp/dismiss')).toHaveLength(1));
    expect(calls.find((call) => call.url === '/api/account/notices/smtp/dismiss')?.method).toBe('POST');
    expect(screen.queryByTestId('smtp-banner')).not.toBeInTheDocument();
  });

  it('keeps the banner closed for the session when the server call fails, without an error popup', async () => {
    const { calls } = mockApi({ ...signedInAs(ADMIN), 'GET /api/setup/status': instanceWith({ mail_enabled: false }),
      'POST /api/account/notices/smtp/dismiss': { status: 500, body: { detail: { code: 'internal' } } }, ...BASE });
    renderShell();
    await screen.findByText(t('shell.smtpBanner'));
    await userEvent.setup().click(screen.getByRole('button', { name: t('shell.smtpBanner.close') }));
    await vi.waitFor(() => expect(calls.some((call) => call.url === '/api/account/notices/smtp/dismiss')).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText(t('shell.smtpBanner'))).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not show the banner to an admin who already dismissed it', async () => {
    mockApi({ ...signedInAs({ ...ADMIN, smtp_notice_dismissed: true }), 'GET /api/setup/status': instanceWith({ mail_enabled: false }), ...BASE });
    renderShell();
    await avatar();
    expect(screen.queryByText(t('shell.smtpBanner'))).not.toBeInTheDocument();
  });

  it('hides the banner when mail works or the user is not an admin', async () => {
    mockApi({ ...signedInAs(ADMIN), ...BASE }); // mail_enabled: true
    const { unmount } = renderShell();
    await avatar();
    expect(screen.queryByText(t('shell.smtpBanner'))).not.toBeInTheDocument();
    unmount();
    mockApi({ ...SIGNED_IN, 'GET /api/setup/status': instanceWith({ mail_enabled: false }), ...BASE });
    renderShell();
    await avatar();
    expect(screen.queryByText(t('shell.smtpBanner'))).not.toBeInTheDocument();
  });

  it('offers the Hệ thống menu item only to an admin', async () => {
    mockApi({ ...signedInAs(ADMIN), ...BASE });
    renderShell();
    const user = userEvent.setup();
    await user.click(await avatar());
    await user.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: t('shell.system') }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings\/system$/);
  });
});
