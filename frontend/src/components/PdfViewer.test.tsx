import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { describe, expect, it, vi } from 'vitest';
import { fileItem } from '../test/fixtures';
import { t } from '../i18n/t';
import { PdfViewer } from './PdfViewer';

function stubMatchMedia(initialMatches: boolean) {
  const listeners = new Set<() => void>();
  let matches = initialMatches;
  const mql = {
    get matches() { return matches; },
    media: '(min-width: 1024px)',
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: (_event: string, cb: () => void) => listeners.add(cb),
    removeEventListener: (_event: string, cb: () => void) => listeners.delete(cb),
    dispatchEvent: () => false,
  };
  vi.stubGlobal('matchMedia', vi.fn(() => mql));
  return {
    setMatches(next: boolean) {
      matches = next;
      listeners.forEach((cb) => cb());
    },
  };
}

const FINISHED = '2026-10-02T10:00:00Z';

function viewer(overrides: Parameters<typeof fileItem>[0] = {}) {
  const item = fileItem({ id: 'f1', filename: 'bao-cao.pdf', finished_at: FINISHED, ...overrides });
  return (
    <GamutProvider theme={theme}>
      <PdfViewer item={item} />
    </GamutProvider>
  );
}

const renderViewer = (overrides: Parameters<typeof fileItem>[0] = {}) => render(viewer(overrides));

const frameTitle = (kind: string) => t('viewer.frameTitle', { name: 'bao-cao.pdf', kind });

describe('PdfViewer', () => {
  it('shows the translated frame by default with the inline URL', () => {
    stubMatchMedia(false);
    renderViewer();
    const frame = screen.getByTitle(frameTitle(t('viewer.translated')));
    expect(frame).toHaveAttribute('src', '/api/files/f1/download?kind=translated&inline=1&v=2026-10-02T10%3A00%3A00Z');
  });

  it('changes the translated frame address when a rebuild finishes, not the original one', async () => {
    stubMatchMedia(false);
    const { rerender } = renderViewer();
    rerender(viewer({ finished_at: '2026-10-02T11:30:00Z' }));
    expect(screen.getByTitle(frameTitle(t('viewer.translated'))))
      .toHaveAttribute('src', '/api/files/f1/download?kind=translated&inline=1&v=2026-10-02T11%3A30%3A00Z');
    await userEvent.setup().click(screen.getByRole('tab', { name: t('viewer.original') }));
    expect(await screen.findByTitle(frameTitle(t('viewer.original'))))
      .toHaveAttribute('src', '/api/files/f1/download?kind=original&inline=1');
  });

  it('switches to the original frame when "Bản gốc" is selected', async () => {
    stubMatchMedia(false);
    renderViewer();
    await userEvent.setup().click(screen.getByRole('tab', { name: t('viewer.original') }));
    const frame = await screen.findByTitle(frameTitle(t('viewer.original')));
    expect(frame).toHaveAttribute('src', '/api/files/f1/download?kind=original&inline=1');
    expect(screen.queryByTitle(frameTitle(t('viewer.translated')))).not.toBeInTheDocument();
  });

  it('does not offer "So sánh" on narrow screens', () => {
    stubMatchMedia(false);
    renderViewer();
    expect(screen.queryByRole('tab', { name: t('viewer.compare') })).not.toBeInTheDocument();
  });

  it('offers "So sánh" on wide screens and shows both frames side by side', async () => {
    stubMatchMedia(true);
    renderViewer();
    await userEvent.setup().click(screen.getByRole('tab', { name: t('viewer.compare') }));
    expect(await screen.findByTitle(frameTitle(t('viewer.original')))).toBeInTheDocument();
    expect(screen.getByTitle(frameTitle(t('viewer.translated')))).toBeInTheDocument();
  });

  it('falls back to "Bản dịch" when the screen shrinks while comparing', async () => {
    const media = stubMatchMedia(true);
    renderViewer();
    await userEvent.setup().click(screen.getByRole('tab', { name: t('viewer.compare') }));
    expect(await screen.findByTitle(frameTitle(t('viewer.original')))).toBeInTheDocument();

    act(() => media.setMatches(false));

    expect(await screen.findByRole('tab', { name: t('viewer.translated'), selected: true })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: t('viewer.compare') })).not.toBeInTheDocument();
    expect(screen.getByTitle(frameTitle(t('viewer.translated')))).toBeInTheDocument();
  });

  it('"Mở trong tab mới" follows the active view', async () => {
    stubMatchMedia(false);
    renderViewer();
    expect(screen.getByRole('link', { name: t('viewer.openNewTab') }))
      .toHaveAttribute('href', '/api/files/f1/download?kind=translated&inline=1');
    await userEvent.setup().click(screen.getByRole('tab', { name: t('viewer.original') }));
    expect(await screen.findByRole('link', { name: t('viewer.openNewTab') }))
      .toHaveAttribute('href', '/api/files/f1/download?kind=original&inline=1');
  });
});
