import type { Me } from './auth';
import { apiFetch, jsonBody } from './client';

/** GET /api/setup/status — công khai, nạp một lần cùng `me` (AuthContext). */
export type InstanceStatus = {
  needs_setup: boolean; // bảng users trống → mọi đường dẫn về /setup
  setup_token_required: boolean; // env SETUP_TOKEN có đặt → wizard hỏi "Mã cài đặt"
  registration_open: boolean;
  mail_enabled: boolean; // false = không SMTP: tài khoản mới dùng ngay, forgot/resend/đổi email bị 409
};
export type SetupBody = { display_name: string | null; email: string; password: string; setup_token?: string };

export const setupApi = {
  status: () => apiFetch<InstanceStatus>('/api/setup/status'),
  create: (body: SetupBody) => apiFetch<Me>('/api/setup', { method: 'POST', body: jsonBody(body) }),
};
