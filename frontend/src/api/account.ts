import type { Me } from './auth';
import { apiFetch, jsonBody } from './client';

type Accepted = { status: 'accepted' };

const send = <T,>(method: 'POST' | 'PUT', path: string, data: unknown) =>
  apiFetch<T>(path, { method, body: jsonBody(data) });

/** Cài đặt › Tài khoản (`/api/account/*`, cần đăng nhập). Xác nhận đổi email nằm ở `authApi.confirmEmail`. */
export const accountApi = {
  saveProfile: (display_name: string) => send<Me>('PUT', '/api/account/profile', { display_name }),
  changePassword: (current_password: string, new_password: string) =>
    send<void>('POST', '/api/account/password', { current_password, new_password }),
  requestEmailChange: (new_email: string, password: string) =>
    send<Accepted>('POST', '/api/account/email', { new_email, password }),
  dismissSmtpNotice: () => send<void>('POST', '/api/account/notices/smtp/dismiss', undefined),
  deleteAccount: (password: string) => send<void>('POST', '/api/account/delete', { password }),
};
