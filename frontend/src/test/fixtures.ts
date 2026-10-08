import type { Me } from '../api/auth';
import type { FileItem, FilePage, Meta } from '../api/files';
import type { CredentialInfo, EngineInfo, ModelInfo, SettingsInfo } from '../api/settings';
import type { InstanceStatus } from '../api/setup';
import type { SystemSettings } from '../api/system';
import type { Handler } from './mockApi';

export const ENGINES: EngineInfo[] = [
  { id: 'google_free', mode: 'plain', label: 'Google miễn phí', needs_key: false },
  { id: 'google_cloud', mode: 'plain', label: 'Google Cloud Translation', needs_key: true },
  { id: 'gemini', mode: 'ai', label: 'Gemini (Google AI Studio)', needs_key: true },
];
export const GEMINI_MODELS: ModelInfo[] = [
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite — rẻ, nhanh (khuyến nghị)' },
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash — chất lượng cao hơn' },
  { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { id: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro (preview) — văn bản khó, đắt' },
];

export const META: Meta = {
  languages: [
    { code: 'vi', name: 'Tiếng Việt' },
    { code: 'en', name: 'Tiếng Anh' },
  ],
  default_language: 'vi',
  max_upload_mb: 1,
  source_url: '',
  engines: ENGINES,
  gemini_models: GEMINI_MODELS,
};

export const INSTANCE: InstanceStatus = { needs_setup: false, setup_token_required: false, registration_open: true, mail_enabled: true };
export const instanceWith = (overrides: Partial<InstanceStatus>): Handler => ({ body: { ...INSTANCE, ...overrides } });
export const ME: Me = { id: 'u1', email: 'an@example.com', display_name: null, is_admin: false, smtp_notice_dismissed: false };
export const ADMIN: Me = { id: 'u0', email: 'admin@example.com', display_name: 'Quản trị', is_admin: true, smtp_notice_dismissed: false };
export const SIGNED_IN: Record<string, Handler> = { 'GET /api/auth/me': { body: ME }, 'GET /api/setup/status': { body: INSTANCE } };
export const signedInAs = (overrides: Partial<Me>): Record<string, Handler> => ({
  'GET /api/auth/me': { body: { ...ME, ...overrides } }, 'GET /api/setup/status': { body: INSTANCE },
});
export const GUEST: Record<string, Handler> = {
  'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated' } } }, 'GET /api/setup/status': { body: INSTANCE },
};
export const SYSTEM: SystemSettings = {
  smtp: { source: 'none', host: '', port: 587, security: 'starttls', username: '', from: '', password_status: 'none' },
  registration_open: true, max_pending_per_user: null, max_pending_default: 3,
  site_url: 'https://pdf.example.com', site_url_source: 'env',
};
export const systemWith = (overrides: Omit<Partial<SystemSettings>, 'smtp'> & { smtp?: Partial<SystemSettings['smtp']> }): SystemSettings =>
  ({ ...SYSTEM, ...overrides, smtp: { ...SYSTEM.smtp, ...(overrides.smtp ?? {}) } });

export const SETTINGS: SettingsInfo = {
  default_engine: 'google_free',
  default_model: null,
  default_font: 'auto',
  engines: ENGINES.map((engine) => ({ ...engine, available: !engine.needs_key })),
  gemini_models: GEMINI_MODELS,
  credentials: [],
};

export const GEMINI_CREDENTIAL: CredentialInfo = {
  provider: 'gemini',
  hint: 'abcd',
  verified_at: new Date().toISOString(),
  models: [GEMINI_MODELS[0], GEMINI_MODELS[1]],
};

export function settingsWith(overrides: Partial<SettingsInfo>): SettingsInfo {
  return { ...SETTINGS, ...overrides };
}

export const SETTINGS_WITH_GEMINI: SettingsInfo = settingsWith({
  default_engine: 'gemini',
  default_model: 'gemini-3.5-flash-lite',
  engines: ENGINES.map((engine) => ({ ...engine, available: engine.id !== 'google_cloud' })),
  gemini_models: [GEMINI_MODELS[0], GEMINI_MODELS[1]],
  credentials: [GEMINI_CREDENTIAL],
});

export function fileItem(overrides: Partial<FileItem> = {}): FileItem {
  const now = new Date().toISOString();
  return {
    id: 'f00000000001', filename: 'Báo cáo.pdf', language: 'vi', status: 'done',
    engine: 'google_free', model: null, stage: '',
    done_pages: 2, total_pages: 2, untranslated: 0, message: 'Xong',
    created_at: now, finished_at: now,
    font: 'auto', font_used: null, rebuild_font: null, rebuilding: false, rebuild_error: '',
    retranslating: false, retranslate_to: null, ...overrides,
  };
}

export function filePage(items: FileItem[], total = items.length, page = 1): FilePage {
  return { items, total, page, page_size: 20 };
}
