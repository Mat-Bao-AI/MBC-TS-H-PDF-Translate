import { apiFetch, jsonBody } from './client';

export type Me = { id: string; email: string; display_name: string | null; is_admin: boolean; smtp_notice_dismissed: boolean; advance_mode: boolean };
/** Xác nhận email từ trình duyệt khác với trình duyệt đã xin link: email đã xác nhận, nhưng KHÔNG đăng nhập. */
export type Verified = { status: 'verified' };
type Accepted = { status: 'accepted' };

const post = <T,>(path: string, data?: unknown) =>
  apiFetch<T>(path, { method: 'POST', body: data === undefined ? undefined : jsonBody(data) });

export const authApi = {
  me: () => apiFetch<Me>('/api/auth/me'),
  login: (email: string, password: string) => post<Me>('/api/auth/login', { email, password }),
  register: (email: string, password: string) => post<Accepted>('/api/auth/register', { email, password }),
  verifyEmail: (token: string) => post<Me | Verified>('/api/auth/verify-email', { token }),
  confirmEmail: (token: string) => post<Me>('/api/auth/confirm-email', { token }),
  resendVerification: (email: string) => post<Accepted>('/api/auth/resend-verification', { email }),
  forgotPassword: (email: string) => post<Accepted>('/api/auth/forgot-password', { email }),
  resetPassword: (token: string, password: string) => post<void>('/api/auth/reset-password', { token, password }),
  logout: () => post<void>('/api/auth/logout'),
};
