import type { Me } from '../api/auth';
import type { FileItem, FilePage, FileVersion, Meta, Snapshot } from '../api/files';
import type { CredentialInfo, EngineInfo, ModelInfo, ProfileItem, SettingsInfo } from '../api/settings';
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
export const ME: Me = { id: 'u1', email: 'an@example.com', display_name: null, is_admin: false, smtp_notice_dismissed: false, advance_mode: false };
export const ADMIN: Me = { id: 'u0', email: 'admin@example.com', display_name: 'Quản trị', is_admin: true, smtp_notice_dismissed: false, advance_mode: false };
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
  max_versions: null, max_versions_default: 3,
  site_url: 'https://pdf.example.com', site_url_source: 'env',
};
export const systemWith = (overrides: Omit<Partial<SystemSettings>, 'smtp'> & { smtp?: Partial<SystemSettings['smtp']> }): SystemSettings =>
  ({ ...SYSTEM, ...overrides, smtp: { ...SYSTEM.smtp, ...(overrides.smtp ?? {}) } });

const preset = (id: string, name: string, style: Omit<ProfileItem, 'id' | 'kind' | 'name' | 'preset_slug' | 'created_at' | 'updated_at'>): ProfileItem =>
  ({ id: `preset:${id}`, kind: 'preset', name, preset_slug: null, created_at: null, updated_at: null, ...style });
/** Y hệt app.profiles.presets của backend (thứ tự = thứ tự hiển thị). */
export const PRESETS: ProfileItem[] = [
  preset('quick', 'Đọc nhanh, tự nhiên', { fidelity: 'natural', tone: 'friendly', audience: 'self', terms: 'translate', proper_names: 'keep',
    numbers: 'target_convention', dates: 'target_convention', abbreviations: 'expand', custom_instructions: '' }),
  preset('client', 'Chuyên nghiệp gửi khách hàng', { fidelity: 'balanced', tone: 'professional', audience: 'client',
    terms: 'translate_with_original', proper_names: 'keep', numbers: 'target_convention', dates: 'target_convention', abbreviations: 'expand',
    custom_instructions: '' }),
  preset('technical', 'Tài liệu kỹ thuật', { fidelity: 'balanced', tone: 'professional', audience: 'expert', terms: 'keep', proper_names: 'keep',
    numbers: 'keep', dates: 'keep', abbreviations: 'keep',
    custom_instructions: 'Giữ nguyên tên thư viện, hàm, lệnh, tham số, tệp và mọi định danh trong mã.' }),
  preset('beginner', 'Dễ hiểu cho người mới', { fidelity: 'natural', tone: 'simple', audience: 'student', terms: 'translate_with_original',
    proper_names: 'keep', numbers: 'target_convention', dates: 'target_convention', abbreviations: 'expand',
    custom_instructions: 'Ưu tiên câu ngắn, từ thông dụng.' }),
  preset('academic', 'Học thuật, sát nghĩa', { fidelity: 'literal', tone: 'academic', audience: 'expert', terms: 'translate_with_original',
    proper_names: 'keep', numbers: 'keep', dates: 'keep', abbreviations: 'keep', custom_instructions: '' }),
];
/** 5 dòng gieo từ mẫu của một người đã bật Chế độ nâng cao (spec 2026-10-15 §5): id dòng, kind custom, preset_slug = slug. */
export const SEEDED_PROFILES: ProfileItem[] = PRESETS.map((profile, index) => ({
  ...profile, id: `ps${String(index + 1).padStart(10, '0')}`, kind: 'custom' as const, preset_slug: profile.id.slice('preset:'.length),
  created_at: '2026-10-15T08:00:00Z', updated_at: '2026-10-15T08:00:00Z',
}));
export const MY_PROFILE: ProfileItem = {
  id: 'p00000000001', kind: 'custom', name: 'Hợp đồng', preset_slug: null, fidelity: 'balanced', tone: 'professional', audience: 'client',
  terms: 'translate_with_original', proper_names: 'keep', numbers: 'target_convention', dates: 'target_convention', abbreviations: 'expand',
  custom_instructions: 'Giọng trang trọng.', created_at: '2026-10-14T08:00:00Z', updated_at: '2026-10-14T08:00:00Z',
};

export const SETTINGS: SettingsInfo = {
  default_engine: 'google_free',
  default_model: null,
  default_font: 'auto',
  advance_mode: false,
  default_profile: null,
  profiles: PRESETS,
  profile_limit: 20,
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
    retranslating: false, retranslate_to: null, version_no: 1, config: null,
    translated_at: now, restored_from: null, restoring: false, restore_version: null, ...overrides,
  };
}

export function filePage(items: FileItem[], total = items.length, page = 1): FilePage {
  return { items, total, page, page_size: 20 };
}

/** Snapshot của hồ sơ mẫu "Tài liệu kỹ thuật" (không ghi đè) — override từng khoá khi cần. */
export function snapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  const technical = PRESETS[2];
  return {
    schema: 1, mode: 'advanced', profile: { id: technical.id, name: technical.name, kind: 'preset' },
    style: {
      fidelity: technical.fidelity, tone: technical.tone, audience: technical.audience, terms: technical.terms,
      proper_names: technical.proper_names, numbers: technical.numbers, dates: technical.dates, abbreviations: technical.abbreviations,
      custom_instructions: technical.custom_instructions,
    },
    overrides: [], document_context: null, ...overrides,
  };
}

export function fileVersion(overrides: Partial<FileVersion> = {}): FileVersion {
  return {
    id: 'v00000000001', version_no: 1, language: 'vi', engine: 'google_free', model: null, font: 'auto', font_used: 'sans', config: null,
    untranslated: 0, finished_at: null, archived_at: '2026-10-14T09:00:00Z', available: true,
    has_tables: false, translated_at: null, restored_from: null, ...overrides,
  };
}
