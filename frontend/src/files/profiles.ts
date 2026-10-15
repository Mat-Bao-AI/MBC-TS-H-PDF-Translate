import type { Snapshot } from '../api/files';
import type { ProfileItem, StyleField, StyleValues } from '../api/settings';
import messages from '../i18n/vi.json';
import { t, type MessageKey } from '../i18n/t';

/** Cùng danh mục với backend (app.profiles.presets) — nhãn tiếng Việt nằm trong vi.json (profiles.field.* / profiles.value.*). */
export const ENUM_FIELDS = ['fidelity', 'tone', 'audience', 'terms', 'proper_names', 'numbers', 'dates', 'abbreviations'] as const;
export type EnumField = (typeof ENUM_FIELDS)[number];
export const STYLE_FIELDS: readonly StyleField[] = [...ENUM_FIELDS, 'custom_instructions'];
export const STYLE_OPTIONS: Record<EnumField, readonly string[]> = {
  fidelity: ['literal', 'balanced', 'natural'],
  tone: ['friendly', 'professional', 'academic', 'simple'],
  audience: ['self', 'student', 'client', 'expert'],
  terms: ['keep', 'translate_with_original', 'translate'],
  proper_names: ['keep', 'localize'],
  numbers: ['keep', 'target_convention'],
  dates: ['keep', 'target_convention'],
  abbreviations: ['keep', 'expand'],
};
export const STYLE_DEFAULTS: StyleValues = {
  fidelity: 'balanced', tone: 'professional', audience: 'self', terms: 'translate', proper_names: 'keep',
  numbers: 'target_convention', dates: 'target_convention', abbreviations: 'keep', custom_instructions: '',
};
export const NAME_MAX = 60;
export const CUSTOM_MAX = 1000;
export const CONTEXT_MAX = 2000;

export const fieldLabel = (field: StyleField): string => t(`profiles.field.${field}` as MessageKey);

export function valueLabel(field: EnumField, value: string): string {
  const key = `profiles.value.${field}.${value}`;
  return key in messages ? t(key as MessageKey) : value; // giá trị lạ (snapshot cũ): hiện nguyên mã, không nổ
}

export const valueOptions = (field: EnumField): Record<string, string> =>
  Object.fromEntries(STYLE_OPTIONS[field].map((value) => [value, valueLabel(field, value)]));

export const profileName = (profile: ProfileItem): string =>
  profile.kind === 'preset' ? `${profile.name} (${t('profiles.preset')})` : profile.name;

/** Options cho Select hồ sơ: "Không áp hồ sơ" trước, rồi mẫu + riêng theo thứ tự server trả. */
export const profileOptions = (profiles: ProfileItem[]): Record<string, string> =>
  ({ '': t('profiles.none'), ...Object.fromEntries(profiles.map((profile) => [profile.id, profileName(profile)])) });

/** Tên gợi ý cho bản sao: "<tên> (bản sao)" trong NAME_MAX ký tự (server từ chối tên dài hơn) — cắt bớt phần tên gốc, giữ hậu tố.
 *  Đếm theo code point như server (không cắt đôi cặp surrogate). */
export function cloneName(name: string): string {
  const full = t('profiles.cloneName', { name });
  const excess = [...full].length - NAME_MAX;
  if (excess <= 0) return full;
  const chars = [...name];
  return t('profiles.cloneName', { name: chars.slice(0, Math.max(0, chars.length - excess)).join('').trimEnd() });
}

/** Tham chiếu → hồ sơ trong danh sách: đúng id, hoặc `preset:<slug>` (snapshot / mặc định cũ) → dòng gieo từ mẫu đó — cùng luật với
 *  backend (profiles.service.resolve_ref). */
export const findProfile = (profiles: ProfileItem[], id: string | null | undefined): ProfileItem | null => {
  if (!id) return null;
  const exact = profiles.find((profile) => profile.id === id);
  if (exact) return exact;
  const slug = id.startsWith('preset:') ? id.slice('preset:'.length) : null;
  return slug ? profiles.find((profile) => profile.preset_slug === slug) ?? null : null;
};

/** Dòng gieo từ mẫu (nhãn "Từ mẫu") — khác mẫu trong code (`kind === 'preset'`). */
export const isFromPreset = (profile: ProfileItem): boolean => profile.kind === 'custom' && profile.preset_slug !== null;

export const styleOf = (profile: ProfileItem): StyleValues =>
  Object.fromEntries(STYLE_FIELDS.map((field) => [field, profile[field]])) as StyleValues;

/** Có hồ sơ: chỉ gửi trường KHÁC hồ sơ (server tính lại `overrides` từ đây). */
export const overridesAgainst = (base: StyleValues, style: StyleValues): Partial<StyleValues> =>
  Object.fromEntries(STYLE_FIELDS.filter((field) => style[field] !== base[field]).map((field) => [field, style[field]]));

/** Không hồ sơ: chỉ gửi trường người dùng đã chạm — server lưu đúng những trường đó (spec 2026-10-14 §3). */
export const pickFields = (style: StyleValues, fields: Iterable<StyleField>): Partial<StyleValues> =>
  Object.fromEntries([...fields].map((field) => [field, style[field]]));

export const snapshotProfileName = (config: Snapshot | null | undefined): string | null => config?.profile?.name ?? null;
