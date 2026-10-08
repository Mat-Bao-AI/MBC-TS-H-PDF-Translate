import { apiFetch, jsonBody } from './client';

export type SmtpSource = 'settings' | 'env' | 'none' | 'dev_log';
export type PasswordStatus = 'none' | 'saved' | 'unreadable';
export type SmtpSecurity = 'starttls' | 'ssl' | 'none';
/** Giá trị đang có hiệu lực (DB hoặc env) — không bao giờ có mật khẩu. */
export type SmtpInfo = {
  source: SmtpSource; host: string; port: number; security: SmtpSecurity; username: string; from: string;
  password_status: PasswordStatus;
};
export type SmtpBody = { host: string; port: number; security: SmtpSecurity; username: string; from: string; password?: string };
/** Nguồn địa chỉ trang dùng trong thư: env APP_BASE_URL > ghi lúc /setup; null = chưa biết (thư có liên kết tắt). */
export type SiteUrlSource = 'env' | 'setup';
export type SystemSettings = {
  smtp: SmtpInfo; registration_open: boolean; max_pending_per_user: number | null; max_pending_default: number;
  site_url: string | null; site_url_source: SiteUrlSource | null;
};
export type SystemSettingsBody = { smtp?: SmtpBody; registration_open?: boolean; max_pending_per_user?: number | null };

/** /api/system/* — chỉ quản trị viên (403 admin_required với người thường). */
export const systemApi = {
  get: () => apiFetch<SystemSettings>('/api/system/settings'),
  save: (body: SystemSettingsBody) => apiFetch<SystemSettings>('/api/system/settings', { method: 'PUT', body: jsonBody(body) }),
  clearSmtp: () => apiFetch<void>('/api/system/settings/smtp', { method: 'DELETE' }),
  testMail: (smtp?: SmtpBody) =>
    apiFetch<{ sent_to: string }>('/api/system/smtp/test', { method: 'POST', body: smtp ? jsonBody({ smtp }) : undefined }),
};
