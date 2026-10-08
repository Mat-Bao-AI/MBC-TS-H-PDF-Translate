import { describe, expect, it } from 'vitest';
import { cacheClear, cacheGet, cacheSet } from './swrCache';

describe('swrCache', () => {
  it('stores and returns values by key', () => {
    cacheSet('a', 1);
    expect(cacheGet<number>('a')).toBe(1);
    expect(cacheGet('missing')).toBeUndefined();
  });

  it('clears one prefix or everything', () => {
    cacheSet('files:1', 1);
    cacheSet('files:2', 2);
    cacheSet('settings:x', 3);
    cacheClear('files:');
    expect(cacheGet('files:1')).toBeUndefined();
    expect(cacheGet('settings:x')).toBe(3);
    cacheClear();
    expect(cacheGet('settings:x')).toBeUndefined();
  });

  it('is emptied between tests by setupTests', () => {
    expect(cacheGet('settings:x')).toBeUndefined();
  });
});
