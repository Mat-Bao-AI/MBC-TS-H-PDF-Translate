import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SIGNED_IN } from '../test/fixtures';
import { filesCalls, list, param, renderHome, seeded } from '../test/home';
import { mockApi } from '../test/mockApi';

// Tách file riêng: mỗi file test có jsdom riêng. Emotion chỉ thêm (không gỡ) stylesheet nên trong một file dài
// getComputedStyle / getByRole chậm dần theo số test, các test cuối vượt thời hạn khi máy tải nặng.
beforeEach(() => resetMetaCache());

describe('HomePage — range line and sorting', () => {
  it.each([
    ['/', 45, 20, '1–20 / 45 tệp'],
    ['/?page=3', 45, 5, '41–45 / 45 tệp'],
    ['/', 3, 3, '1–3 / 3 tệp'],
  ])('shows the range under the table at %s', async (at, total, count, expected) => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(count), total) });
    renderHome(at);
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it('shows no range line when there are no files', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list([]) });
    renderHome();
    await screen.findByText(t('home.empty.title'));
    expect(screen.queryByText(/ tệp$/)).not.toBeInTheDocument();
  });

  it('cycles a column asc → desc → default, keeps it in the URL and resets the page', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(3), 45) });
    renderHome('/?page=2');
    const user = userEvent.setup();
    const sortBy = async () => user.click(await screen.findByRole('button', { name: t('table.sortBy', { column: t('home.col.name') }) }));
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    await sortBy();
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/\?sort=name&dir=asc$/));
    await waitFor(() => expect(param(filesCalls(calls).at(-1)!.url, 'sort')).toBe('name'));
    expect(param(filesCalls(calls).at(-1)!.url, 'dir')).toBe('asc');
    expect(param(filesCalls(calls).at(-1)!.url, 'page')).toBe('1');
    expect(screen.getByRole('columnheader', { name: /Tên/ })).toHaveAttribute('aria-sort', 'ascending');
    await sortBy();
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?sort=name&dir=desc'));
    await sortBy();
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/));
    expect(param(filesCalls(calls).at(-1)!.url, 'sort')).toBe('created');
    expect(param(filesCalls(calls).at(-1)!.url, 'dir')).toBe('desc');
  });

  it('sorts by status and by created date; the actions column is not sortable', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(2)) });
    renderHome('/?sort=created&dir=asc');
    const user = userEvent.setup();
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    expect(param(filesCalls(calls)[0].url, 'sort')).toBe('created');
    expect(param(filesCalls(calls)[0].url, 'dir')).toBe('asc');
    await user.click(screen.getByRole('button', { name: t('table.sortBy', { column: t('home.col.status') }) }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?sort=status&dir=asc'));
    expect(screen.queryByRole('button', { name: /^Sắp xếp theo Thao tác/ })).not.toBeInTheDocument();
  });

  it('ignores a junk sort in the URL', async () => {
    const { calls } = mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list(seeded(1)) });
    renderHome('/?sort=bogus&dir=up');
    await screen.findByRole('link', { name: 'tep-1.pdf' });
    expect(param(filesCalls(calls)[0].url, 'sort')).toBe('created');
    expect(param(filesCalls(calls)[0].url, 'dir')).toBe('desc');
  });
});

