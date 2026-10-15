import { apiFetch, jsonBody } from './client';

export type EngineMode = 'plain' | 'ai';
export type Provider = 'google_cloud' | 'gemini';
export type EngineInfo = { id: string; mode: EngineMode; label: string; needs_key: boolean; available?: boolean };
export type ModelInfo = { id: string; label: string };
export type CredentialInfo = { provider: Provider; hint: string; verified_at: string; models: ModelInfo[] };
/** 9 trường của một hồ sơ dịch (spec 2026-10-14 §2); 8 trường đầu là enum, custom_instructions là văn bản ≤ 1000. */
export type StyleField = 'fidelity' | 'tone' | 'audience' | 'terms' | 'proper_names' | 'numbers' | 'dates' | 'abbreviations' | 'custom_instructions';
export type StyleValues = Record<StyleField, string>;
export type ProfileKind = 'preset' | 'custom';
/** Mẫu (`preset:<slug>`, chỉ đọc, created_at null) hoặc hồ sơ riêng — cùng dáng ở GET /api/profiles và settings.profiles. */
export type ProfileItem = StyleValues & { id: string; kind: ProfileKind; name: string; preset_slug: string | null; created_at: string | null; updated_at: string | null };
export type ProfileBody = Partial<StyleValues> & { name: string };
export type SettingsInfo = {
  default_engine: string;
  default_model: string | null;
  default_font: string;
  advance_mode: boolean;
  default_profile: string | null; // tham chiếu treo đã được server đọc như null
  profiles: ProfileItem[];
  profile_limit: number;
  engines: EngineInfo[];
  gemini_models: ModelInfo[];
  credentials: CredentialInfo[];
};

/** Thân PUT /api/settings/preferences: default_engine bắt buộc; trường bỏ qua = giữ nguyên; default_profile null = bỏ hồ sơ mặc định. */
export type PreferencesBody = {
  default_engine: string; default_model: string | null; default_font?: string; advance_mode?: boolean; default_profile?: string | null;
};

/** Khoá bộ nhớ đệm của GET /api/settings — trang Dịch thuật và trang Hồ sơ dịch dùng chung để làm mới đúng chỗ. */
export const TRANSLATION_SETTINGS_CACHE_KEY = 'settings:translation';

const credential = (provider: Provider) => `/api/settings/credentials/${provider}`;

export const settingsApi = {
  get: () => apiFetch<SettingsInfo>('/api/settings'),
  savePreferences: (body: PreferencesBody) =>
    apiFetch<SettingsInfo>('/api/settings/preferences', { method: 'PUT', body: jsonBody(body) }),
  saveKey: (provider: Provider, api_key: string) =>
    apiFetch<SettingsInfo>(credential(provider), { method: 'PUT', body: jsonBody({ api_key }) }),
  deleteKey: (provider: Provider) => apiFetch<void>(credential(provider), { method: 'DELETE' }),
};
