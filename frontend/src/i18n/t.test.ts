import { describe, expect, it } from 'vitest';
import { errorText, t } from './t';

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
