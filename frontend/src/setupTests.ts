import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { cacheClear } from './lib/swrCache';

// Gamut đọc prefers-color-scheme lúc render; jsdom không có matchMedia.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }),
});
if (!('ResizeObserver' in window)) {
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// findBy*/waitFor đợi tối đa 5 s thay vì 1 s mặc định: node dùng chung tải nặng, lượt render đầu của trang Gamut
// có lúc quá 1 s → rớt ngẫu nhiên. Test đúng vẫn xong ngay khi phần tử xuất hiện; chỉ test sai mới chờ lâu hơn.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  cacheClear(); // bộ nhớ đệm trang không được rò từ test này sang test khác
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
