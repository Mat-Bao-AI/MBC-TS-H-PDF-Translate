import { theme } from '@codecademy/gamut-styles';

// Be Vietnam Pro (SIL OFL-1.1) tự lưu trữ qua @fontsource — thay Apercu/Suisse (font thương mại tải từ codecademy.com).
export const FONT_STACK =
  '"Be Vietnam Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

// Cả slot `base` lẫn `accent` (trước là Suisse mono) cùng dùng một họ chữ sans; `monospace`/`system` giữ nguyên của Gamut.
// CoreTheme gõ fontFamily bằng literal của Apercu/Suisse (không so sánh được với chuỗi mới) nên cần `as unknown as`; kiểu kết quả vẫn là CoreTheme cho component Gamut.
export const appTheme = {
  ...theme,
  fontFamily: { ...theme.fontFamily, base: FONT_STACK, accent: FONT_STACK },
} as unknown as typeof theme;
