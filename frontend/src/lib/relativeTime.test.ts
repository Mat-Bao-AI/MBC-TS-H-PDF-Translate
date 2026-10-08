import { describe, expect, it } from 'vitest';
import { formatRelative } from './relativeTime';

// 30/9/2026 là thứ Tư. Dựng bằng giờ địa phương nên test không phụ thuộc múi giờ máy chạy.
const now = new Date(2026, 8, 30, 10, 0);
const at = (...parts: [number, number, number, number, number]) => new Date(...parts).toISOString();

describe('formatRelative', () => {
  it('today', () => expect(formatRelative(at(2026, 8, 30, 8, 5), now)).toBe('hôm nay lúc 08:05'));
  it('yesterday', () => expect(formatRelative(at(2026, 8, 29, 18, 46), now)).toBe('hôm qua lúc 18:46'));
  it('this week', () => expect(formatRelative(at(2026, 8, 26, 16, 13), now)).toBe('Thứ Bảy lúc 16:13'));
  it('this year', () => expect(formatRelative(at(2026, 8, 15, 9, 0), now)).toBe('15/9'));
  it('older', () => expect(formatRelative(at(2025, 11, 31, 9, 0), now)).toBe('31/12/2025'));
});
