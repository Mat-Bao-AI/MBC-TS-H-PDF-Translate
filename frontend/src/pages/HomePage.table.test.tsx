import { screen } from '@testing-library/react';
import { breakpoints } from '@codecademy/gamut-styles';
import { beforeEach, describe, expect, it } from 'vitest';
import { t } from '../i18n/t';
import { resetMetaCache } from '../files/useMeta';
import { META, SIGNED_IN, fileItem } from '../test/fixtures';
import { mockApi } from '../test/mockApi';
import { list, renderHome } from '../test/home';

beforeEach(() => resetMetaCache());

const LONG = 'Phishing_Report_pointmeme.com.pdf';

// jsdom không đo được bố cục — kiểm các luật CSS tính ra, là thứ quyết định cột thẳng hàng / tên bị cắt trên trình duyệt thật.
describe('HomePage file table layout', () => {
  async function renderTable() {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list([fileItem({ id: 'f00000000001', filename: LONG })]) });
    renderHome();
    return screen.findByRole('link', { name: LONG });
  }

  const allRules = () => Array.from(document.styleSheets).flatMap((sheet) => Array.from(sheet.cssRules).map((rule) => rule.cssText));
  const flat = (text: string) => text.replace(/\s+/g, ' ');
  // jsdom ignores @container rules, so read the emotion-generated CSSOM text of the horizontal-layout block instead.
  const horizontalCss = () => {
    const block = allRules().find((rule) => rule.startsWith(`@container (min-width: ${breakpoints.sm})`) && rule.includes('thead tr>td:first-of-type'));
    expect(block).toBeDefined();
    return flat(block as string);
  };
  const rowOf = (link: HTMLElement) => link.closest('tr') as HTMLElement;
  const tableOf = (link: HTMLElement) => link.closest('table') as HTMLElement;

  it('targets the header select-all cell, only in the horizontal layout', async () => {
    const link = await renderTable();
    const target = tableOf(link).querySelector('thead tr > td:first-of-type');
    expect(target).toContainElement(screen.getByRole('checkbox', { name: t('table.selectAll') }));
    expect(target?.tagName).toBe('TD');
    expect(horizontalCss()).toMatch(/thead tr>td:first-of-type \{ padding-right: 0px; \}/);
  });

  it('targets the name cells (header holds the sort control, body holds the link) and clips only the body one', async () => {
    const link = await renderTable();
    const table = tableOf(link);
    expect(table.querySelectorAll('thead tr > th:first-of-type')).toHaveLength(1);
    expect(table.querySelector('thead tr > th:first-of-type')).toContainElement(screen.getByRole('button', { name: t('table.sortBy', { column: t('home.col.name') }) }));
    expect(table.querySelectorAll('tbody tr > th:first-of-type')).toHaveLength(1);
    expect(link.closest('th')).toBe(rowOf(link).querySelector('th:first-of-type'));
    expect(link.closest('th')).toBe(table.querySelector('tbody tr > th:first-of-type'));
    const css = horizontalCss();
    expect(css).toMatch(/thead tr>th:first-of-type \{ flex: 1 1 0px; min-width: 0px; \}/);
    expect(css).toMatch(/tbody tr>th:first-of-type \{ flex: 1 1 0px; min-width: 0px; overflow: hidden; \}/);
  });

  it('keeps the name-column overrides out of the stacked layout (no unscoped th:first-of-type rule)', async () => {
    await renderTable();
    const unscoped = allRules().filter((rule) => !rule.startsWith('@container') && rule.includes('th:first-of-type') && /gamut-/.test(rule) && /flex: 1 1 0/.test(rule));
    expect(unscoped).toEqual([]);
  });

  it('shows a long filename on one ellipsized line with the full name as tooltip', async () => {
    const link = await renderTable();
    const line = link.parentElement as HTMLElement;
    const text = link.firstElementChild as HTMLElement;
    expect(text).toHaveTextContent(LONG);
    expect(getComputedStyle(link).display).toBe('block'); // Gamut's inline-block anchor would wrap at hyphens
    expect(getComputedStyle(link).overflow).not.toBe('hidden'); // would clip the focus ring
    const style = getComputedStyle(text);
    expect(style.textOverflow).toBe('ellipsis');
    expect(style.whiteSpace).toBe('nowrap');
    expect(style.overflow).toBe('hidden');
    expect(style.display).toBe('block');
    expect(line).toHaveAttribute('title', LONG);
    expect(link).toHaveAccessibleName(LONG);
  });
});
