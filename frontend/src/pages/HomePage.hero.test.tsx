import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SETTINGS, SIGNED_IN, fileItem } from '../test/fixtures';
import { list, renderHome } from '../test/home';
import { mockApi } from '../test/mockApi';

// Tách file riêng: mỗi file test có jsdom riêng. Emotion chỉ thêm (không gỡ) stylesheet nên trong một file dài
// getComputedStyle / getByRole chậm dần theo số test, các test cuối vượt thời hạn khi máy tải nặng.
beforeEach(() => resetMetaCache());

describe('HomePage — hero drop zone', () => {
  const pdf = (name: string, size = 10) => new File([new Uint8Array(size)], name, { type: 'application/pdf' });

  it('opens the upload dialog with a dropped PDF already selected', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS }, 'GET /api/files': list([fileItem()]) });
    renderHome();
    fireEvent.drop(await screen.findByTestId('hero-dropzone'), { dataTransfer: { files: [pdf('keo-tha.pdf')] } });
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('upload.selected', { name: 'keo-tha.pdf' }))).toBeInTheDocument();
  });

  it('opens the dialog with a PDF picked through the zone link', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS }, 'GET /api/files': list([fileItem()]) });
    renderHome();
    await userEvent.setup().upload(await screen.findByTestId('hero-file-input'), pdf('chon.pdf'));
    expect(within(await screen.findByRole('dialog')).getByText(t('upload.selected', { name: 'chon.pdf' }))).toBeInTheDocument();
  });

  it('shows an error under the zone and no dialog for a wrong file', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list([fileItem()]) });
    renderHome();
    fireEvent.drop(await screen.findByTestId('hero-dropzone'), { dataTransfer: { files: [new File(['x'], 'a.txt')] } });
    expect(screen.getByText(t('error.not_pdf'))).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('has no separate upload button any more besides the empty-state one', async () => {
    mockApi({ ...SIGNED_IN, 'GET /api/meta': { body: META }, 'GET /api/files': list([fileItem()]) });
    renderHome();
    await screen.findByRole('link', { name: 'Báo cáo.pdf' });
    expect(screen.queryByRole('button', { name: t('home.upload') })).not.toBeInTheDocument();
  });
});
