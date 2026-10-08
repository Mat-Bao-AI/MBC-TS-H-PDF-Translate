import { describe, expect, it } from 'vitest';
import { safeNext } from './safeNext';

describe('safeNext', () => {
  it('keeps same-site paths', () => {
    expect(safeNext('/files/abc?x=1')).toBe('/files/abc?x=1');
  });
  it.each([null, '', '//evil.com', '/\\evil.com', 'https://evil.com', 'javascript:alert(1)'])(
    'falls back to / for %s',
    (raw) => {
      expect(safeNext(raw)).toBe('/');
    },
  );
});
