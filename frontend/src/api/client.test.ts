import { describe, expect, it, vi } from 'vitest';
import { mockApi } from '../test/mockApi';
import { ApiError, AUTH_EXPIRED_EVENT, INSTANCE_STALE_EVENT, apiFetch, jsonBody } from './client';

describe('apiFetch', () => {
  it('sends the CSRF header and a JSON content type for JSON bodies', async () => {
    const { calls } = mockApi({ 'POST /api/x': { body: { ok: true } } });
    await expect(apiFetch('/api/x', { method: 'POST', body: jsonBody({ a: 1 }) })).resolves.toEqual({ ok: true });
    expect(calls[0].headers.get('X-Requested-With')).toBe('fetch');
    expect(calls[0].headers.get('Content-Type')).toBe('application/json');
  });

  it('leaves the content type alone for FormData', async () => {
    const { calls } = mockApi({ 'POST /api/files': { status: 202, body: {} } });
    await apiFetch('/api/files', { method: 'POST', body: new FormData() });
    expect(calls[0].headers.get('Content-Type')).toBeNull();
  });

  it('turns error detail into ApiError with params', async () => {
    mockApi({ 'POST /api/files': { status: 413, body: { detail: { code: 'too_large', mb: 50 } } } });
    const error = await apiFetch('/api/files', { method: 'POST' }).catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 413, code: 'too_large', params: { mb: 50 } });
  });

  it('maps validation errors and network failures', async () => {
    mockApi({ 'POST /api/x': { status: 422, body: { detail: [{ loc: ['body'] }] } } });
    await expect(apiFetch('/api/x', { method: 'POST' })).rejects.toMatchObject({ code: 'validation' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(apiFetch('/api/x')).rejects.toMatchObject({ status: 0, code: 'network' });
  });

  it.each([
    [409, 'setup_required'], [409, 'setup_done'], [403, 'registration_closed'], [409, 'mail_not_configured'],
  ])('announces a stale instance status on %i %s', async (status, code) => {
    mockApi({ 'POST /api/x': { status, body: { detail: { code } } } });
    const listener = vi.fn();
    window.addEventListener(INSTANCE_STALE_EVENT, listener);
    await expect(apiFetch('/api/x', { method: 'POST' })).rejects.toMatchObject({ status, code });
    window.removeEventListener(INSTANCE_STALE_EVENT, listener);
    expect(listener).toHaveBeenCalledOnce();
  });

  it('does not announce a stale instance status for other errors', async () => {
    mockApi({ 'POST /api/x': { status: 409, body: { detail: { code: 'file_running' } } } });
    const listener = vi.fn();
    window.addEventListener(INSTANCE_STALE_EVENT, listener);
    await apiFetch('/api/x', { method: 'POST' }).catch(() => undefined);
    window.removeEventListener(INSTANCE_STALE_EVENT, listener);
    expect(listener).not.toHaveBeenCalled();
  });

  it('announces an expired session', async () => {
    mockApi({ 'GET /api/files': { status: 401, body: { detail: { code: 'unauthenticated' } } } });
    const listener = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, listener);
    await apiFetch('/api/files').catch(() => undefined);
    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
    expect(listener).toHaveBeenCalledOnce();
  });

  it('returns undefined for 204', async () => {
    mockApi({ 'POST /api/auth/logout': { status: 204 } });
    await expect(apiFetch('/api/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });
});
