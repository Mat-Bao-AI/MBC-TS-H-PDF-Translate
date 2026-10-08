import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { describe, expect, it, vi } from 'vitest';
import { t } from '../i18n/t';
import { META } from '../test/fixtures';
import { HeroDropZone } from './HeroDropZone';

const pdf = (name = 'Báo cáo.pdf', size = 10) => new File([new Uint8Array(size)], name, { type: 'application/pdf' });

function renderZone() {
  const onFile = vi.fn();
  render(<GamutProvider theme={theme}><HeroDropZone meta={META} onFile={onFile} /></GamutProvider>);
  return { onFile };
}

describe('HeroDropZone', () => {
  it('shows exactly one instruction line with a link-styled button', () => {
    renderZone();
    const zone = screen.getByTestId('hero-dropzone');
    expect(zone).toHaveTextContent(t('home.drop', { link: t('home.drop.link') }));
    expect(screen.getByRole('button', { name: t('home.drop.link') })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('opens the file picker from the button and from a click anywhere in the zone', async () => {
    renderZone();
    const input = screen.getByTestId('hero-file-input') as HTMLInputElement;
    const click = vi.spyOn(input, 'click').mockImplementation(() => {});
    await userEvent.setup().click(screen.getByRole('button', { name: t('home.drop.link') }));
    expect(click).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('hero-dropzone'));
    expect(click).toHaveBeenCalledTimes(2);
  });

  it('is reachable and activatable with the keyboard', async () => {
    renderZone();
    const input = screen.getByTestId('hero-file-input') as HTMLInputElement;
    const click = vi.spyOn(input, 'click').mockImplementation(() => {});
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole('button', { name: t('home.drop.link') })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(click).toHaveBeenCalledTimes(1);
  });

  it('hands a dropped PDF to the parent', () => {
    const { onFile } = renderZone();
    const file = pdf('keo-tha.pdf');
    fireEvent.drop(screen.getByTestId('hero-dropzone'), { dataTransfer: { files: [file] } });
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it('hands over a picked PDF', async () => {
    const { onFile } = renderZone();
    const file = pdf('chon.pdf');
    await userEvent.setup().upload(screen.getByTestId('hero-file-input'), file);
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it('shows an inline error for a non-PDF or oversize file and does not hand it over', () => {
    const { onFile } = renderZone();
    const zone = screen.getByTestId('hero-dropzone');
    fireEvent.drop(zone, { dataTransfer: { files: [new File(['x'], 'ghi-chu.txt')] } });
    expect(screen.getByRole('alert')).toHaveTextContent(t('error.not_pdf'));
    fireEvent.drop(zone, { dataTransfer: { files: [pdf('to.pdf', 2 * 1024 * 1024)] } });
    expect(screen.getByRole('alert')).toHaveTextContent(t('error.too_large', { mb: 1 }));
    expect(onFile).not.toHaveBeenCalled();
    fireEvent.drop(zone, { dataTransfer: { files: [pdf()] } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(onFile).toHaveBeenCalledTimes(1);
  });

  it('highlights while a file is dragged over and stops when it leaves or drops', () => {
    renderZone();
    const zone = screen.getByTestId('hero-dropzone');
    expect(zone).toHaveAttribute('data-dragging', 'false');
    fireEvent.dragOver(zone);
    expect(zone).toHaveAttribute('data-dragging', 'true');
    fireEvent.dragLeave(zone);
    expect(zone).toHaveAttribute('data-dragging', 'false');
    fireEvent.dragOver(zone);
    fireEvent.drop(zone, { dataTransfer: { files: [pdf()] } });
    expect(zone).toHaveAttribute('data-dragging', 'false');
  });

  it('keeps the highlight when the pointer only moves onto a child of the zone', () => {
    renderZone();
    const zone = screen.getByTestId('hero-dropzone');
    fireEvent.dragOver(zone);
    fireEvent(zone, new MouseEvent('dragleave', { bubbles: true, relatedTarget: screen.getByRole('button', { name: t('home.drop.link') }) }));
    expect(zone).toHaveAttribute('data-dragging', 'true');
    fireEvent(zone, new MouseEvent('dragleave', { bubbles: true, relatedTarget: document.body }));
    expect(zone).toHaveAttribute('data-dragging', 'false');
  });
});
