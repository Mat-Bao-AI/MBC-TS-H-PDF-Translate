import { apiFetch, jsonBody } from './client';

export type EngineMode = 'plain' | 'ai';
export type Provider = 'google_cloud' | 'gemini';
export type EngineInfo = { id: string; mode: EngineMode; label: string; needs_key: boolean; available?: boolean };
export type ModelInfo = { id: string; label: string };
export type CredentialInfo = { provider: Provider; hint: string; verified_at: string; models: ModelInfo[] };
export type SettingsInfo = {
  default_engine: string;
  default_model: string | null;
  default_font: string;
  engines: EngineInfo[];
  gemini_models: ModelInfo[];
  credentials: CredentialInfo[];
};

const credential = (provider: Provider) => `/api/settings/credentials/${provider}`;

export const settingsApi = {
  get: () => apiFetch<SettingsInfo>('/api/settings'),
  savePreferences: (default_engine: string, default_model: string | null, default_font: string) =>
    apiFetch<SettingsInfo>('/api/settings/preferences', {
      method: 'PUT', body: jsonBody({ default_engine, default_model, default_font }),
    }),
  saveKey: (provider: Provider, api_key: string) =>
    apiFetch<SettingsInfo>(credential(provider), { method: 'PUT', body: jsonBody({ api_key }) }),
  deleteKey: (provider: Provider) => apiFetch<void>(credential(provider), { method: 'DELETE' }),
};
