import { act, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AUTH_EXPIRED_EVENT } from '../api/client';
import { instanceWith } from '../test/fixtures';
import { mockApi } from '../test/mockApi';
import { renderApp } from '../test/render';
import { GuestOnly, RequireAuth } from './RequireAuth';

const routes = (
  <Routes>
    <Route path="/setup" element={<p>trang cài đặt</p>} />
    <Route path="/login" element={<GuestOnly><p>trang đăng nhập</p></GuestOnly>} />
    <Route path="/files/:id" element={<RequireAuth><p>trang tệp</p></RequireAuth>} />
    <Route path="/" element={<RequireAuth><p>trang chính</p></RequireAuth>} />
  </Routes>
);
const GUEST = { 'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated' } } } };
const SIGNED_IN = { 'GET /api/auth/me': { body: { id: 'u1', email: 'an@example.com', is_admin: false } } };

describe('route guards', () => {
  it('sends guests to login and remembers where they were going', async () => {
    mockApi(GUEST);
    renderApp(routes, { at: '/files/abc?x=1' });
    expect(await screen.findByText('trang đăng nhập')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login?next=%2Ffiles%2Fabc%3Fx%3D1');
  });

  it('keeps signed-in users away from the login page', async () => {
    mockApi(SIGNED_IN);
    renderApp(routes, { at: '/login' });
    expect(await screen.findByText('trang chính')).toBeInTheDocument();
  });

  it('drops to login when a later request finds the session expired', async () => {
    mockApi(SIGNED_IN);
    renderApp(routes, { at: '/' });
    await screen.findByText('trang chính');
    act(() => {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    });
    expect(await screen.findByText('trang đăng nhập')).toBeInTheDocument();
  });

  it('keeps working when the instance status cannot be loaded', async () => {
    mockApi({ 'GET /api/auth/me': { body: { id: 'u1', email: 'an@example.com', display_name: null, is_admin: false } },
      'GET /api/setup/status': { status: 500, body: { detail: { code: 'unknown' } } } });
    renderApp(routes, { at: '/' });
    expect(await screen.findByText('trang chính')).toBeInTheDocument(); // lùi về INSTANCE_FALLBACK, không chặn app
  });

  it('sends a guest to /setup while the instance needs setup', async () => {
    mockApi({ ...GUEST, 'GET /api/setup/status': instanceWith({ needs_setup: true }) });
    renderApp(routes, { at: '/login' });
    expect(await screen.findByText('trang cài đặt')).toBeInTheDocument();
  });

  it('sends even a signed-in user to /setup while the instance needs setup', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/setup/status': instanceWith({ needs_setup: true }) });
    renderApp(routes, { at: '/files/abc' });
    expect(await screen.findByText('trang cài đặt')).toBeInTheDocument();
  });
});
