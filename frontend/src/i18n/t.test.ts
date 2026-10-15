import { describe, expect, it } from 'vitest';
import { ENUM_FIELDS } from '../files/profiles';
import { errorText, t, type MessageKey } from './t';

describe('t', () => {
  it('interpolates variables', () => {
    expect(t('home.greeting', { name: 'an' })).toBe('Xin chào, an!');
  });
  it('leaves unknown placeholders visible', () => {
    expect(t('home.greeting')).toBe('Xin chào, {name}!');
  });
  it('maps error codes with params and falls back for unknown codes', () => {
    expect(errorText('too_large', { mb: 50 })).toBe('Tệp vượt quá giới hạn 50MB.');
    expect(errorText('something_new')).toBe(t('error.unknown'));
  });
});

describe('error codes added by the request-limit / rate-limit hardening', () => {
  it('have their own wording', () => {
    expect(errorText('too_many_requests')).toBe('Bạn thao tác quá nhanh. Vui lòng đợi ít phút rồi thử lại.');
    expect(errorText('request_too_large')).toBe('Dữ liệu gửi lên quá lớn.');
  });
});

describe('provider error codes (real cause instead of "key bị từ chối")', () => {
  it('have their own wording', () => {
    expect(errorText('model_unavailable')).toBe('Model này không còn dùng được.');
    expect(errorText('rate_limited')).toBe('Dịch vụ đang giới hạn tốc độ của key này. Thử lại sau ít phút.');
  });
});

describe('invalid_style / invalid_profile name the field by its on-screen label, never the raw key', () => {
  const cases: [string, string, MessageKey][] = [
    ...ENUM_FIELDS.map((field): [string, string, MessageKey] => ['invalid_style', field, `profiles.field.${field}` as MessageKey]),
    ['invalid_style', 'custom_instructions', 'profiles.field.custom_instructions'],
    ['invalid_style', 'context', 'upload.advanced.context'],
    ['invalid_style', 'style', 'profiles.fieldGeneric'],
    ['invalid_style', 'glossary', 'profiles.fieldGeneric'],
    ['invalid_profile', 'name', 'profiles.form.name'],
    ['invalid_profile', 'tone', 'profiles.field.tone'],
    ['invalid_profile', 'custom_instructions', 'profiles.field.custom_instructions'],
  ];
  it.each(cases)('%s field=%s', (code, field, label) => {
    const text = errorText(code, { field });
    expect(text).toBe(t(`error.${code}` as MessageKey, { field: t(label) }));
    expect(text).not.toContain(field);
  });
});
