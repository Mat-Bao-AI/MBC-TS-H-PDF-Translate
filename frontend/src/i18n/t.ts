import messages from './vi.json';

export type MessageKey = keyof typeof messages;

export function t(key: MessageKey, vars: Record<string, string | number> = {}): string {
  return messages[key].replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

export function errorText(code: string, params: Record<string, string | number> = {}): string {
  const key = `error.${code}`;
  return key in messages ? t(key as MessageKey, params) : t('error.unknown');
}
