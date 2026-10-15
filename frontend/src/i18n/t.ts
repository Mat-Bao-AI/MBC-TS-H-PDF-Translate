import messages from './vi.json';

export type MessageKey = keyof typeof messages;

export function t(key: MessageKey, vars: Record<string, string | number> = {}): string {
  return messages[key].replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

/** Mã lỗi kèm `field` là khoá trường của backend: hiện nhãn của ô trên màn hình thay cho mã thô. */
const FIELD_LABELLED_CODES = new Set(['invalid_style', 'invalid_profile']);

/**
 * Nhãn tiếng Việt cho khoá trường backend gửi kèm `invalid_style` / `invalid_profile`: 9 trường hồ sơ → `profiles.field.*`,
 * `context` → ô ngữ cảnh, `name` → ô tên hồ sơ, còn lại (`style`, khoá lạ) → nhãn chung.
 */
export function errorFieldLabel(field: string): string {
  if (field === 'context') return t('upload.advanced.context');
  if (field === 'name') return t('profiles.form.name');
  const key = `profiles.field.${field}`;
  return key in messages ? t(key as MessageKey) : t('profiles.fieldGeneric');
}

export function errorText(code: string, params: Record<string, string | number> = {}): string {
  const key = `error.${code}`;
  if (!(key in messages)) return t('error.unknown');
  const field = params.field;
  const vars = FIELD_LABELLED_CODES.has(code) && typeof field === 'string' ? { ...params, field: errorFieldLabel(field) } : params;
  return t(key as MessageKey, vars);
}
