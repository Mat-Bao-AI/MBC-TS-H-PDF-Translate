import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AppProviders } from './AppProviders';
import { appTheme, FONT_STACK } from './theme';

function allCss(): string {
  return Array.from(document.querySelectorAll('style'))
    .map((el) => {
      const sheet = (el as HTMLStyleElement).sheet;
      const rules = sheet ? Array.from(sheet.cssRules).map((r) => r.cssText).join('\n') : '';
      return `${el.textContent ?? ''}\n${rules}`;
    })
    .join('\n');
}

function renderRoot() {
  return render(
    <AppProviders>
      <h1>Tiêu đề</h1>
    </AppProviders>,
  );
}

describe('theme chữ tự lưu trữ', () => {
  it('base và accent đều dùng Be Vietnam Pro', () => {
    expect(FONT_STACK.startsWith('"Be Vietnam Pro"')).toBe(true);
    expect(appTheme.fontFamily.base).toBe(FONT_STACK);
    expect(appTheme.fontFamily.accent).toBe(FONT_STACK);
  });
});

describe('AppGlobals', () => {
  it('không còn @font-face / URL của Codecademy, Apercu hay Suisse', () => {
    renderRoot();
    const css = allCss();
    expect(css).not.toMatch(/codecademy\.com/i);
    expect(css).not.toMatch(/apercu/i);
    expect(css).not.toMatch(/suisse/i);
    expect(css).not.toMatch(/@font-face/);
  });

  it('Reboot đặt font body đúng FONT_STACK', () => {
    renderRoot();
    const css = allCss().replace(/\s+/g, ' ');
    const body = /(?:^|[ }])body\s*\{([^}]*)\}/.exec(css);
    expect(body, 'không có luật body').not.toBeNull();
    expect(body![1].replace(/\s+/g, ' ')).toContain(`font-family: ${FONT_STACK}`);
  });

  it('vẫn có luật cho h1–h6 và small, và biến CSS của theme', () => {
    renderRoot();
    const css = allCss().replace(/\s+/g, '');
    expect(css).toMatch(/h1,h2,h3,h4,h5,h6\{/);
    for (const tag of ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'small']) {
      expect(css).toMatch(new RegExp(`(^|\\})${tag}\\{font-size:`));
    }
    expect(css).toContain('--color-');
  });
});
