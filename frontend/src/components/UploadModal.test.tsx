import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { META, SETTINGS, SETTINGS_WITH_GEMINI, fileItem, settingsWith } from '../test/fixtures';
import { mockApi } from '../test/mockApi';
import { UploadModal } from './UploadModal';

const pdf = (name = 'Báo cáo.pdf', size = 10) => new File([new Uint8Array(size)], name, { type: 'application/pdf' });
const BASE = { 'GET /api/meta': { body: META }, 'GET /api/settings': { body: SETTINGS } };

function renderModal(initialFile?: File) {
  const onUploaded = vi.fn();
  render(
    <GamutProvider theme={theme}>
      <MemoryRouter>
        <UploadModal isOpen onClose={vi.fn()} onUploaded={onUploaded} initialFile={initialFile} />
      </MemoryRouter>
    </GamutProvider>,
  );
  return { onUploaded };
}

// applyAccept: false — để thử được cả tệp .txt mà ô chọn tệp vốn lọc bỏ.
const setupUser = () => userEvent.setup({ applyAccept: false });
const postedForm = (calls: { method: string; body: unknown }[]) => calls.find((call) => call.method === 'POST')!.body as FormData;
// "Dịch" chỉ bấm được khi yêu cầu cài đặt đã xong (thành công hay lỗi).
const submitReady = async () => {
  const button = screen.getByRole('button', { name: t('upload.submit') });
  await vi.waitFor(() => expect(button).toBeEnabled());
  return button;
};

beforeEach(() => resetMetaCache());

describe('UploadModal', () => {
  it('uploads the chosen PDF in the chosen language with the default engine', async () => {
    const item = fileItem({ status: 'queued' });
    const { calls } = mockApi({ ...BASE, 'POST /api/files': { status: 202, body: item } });
    const { onUploaded } = renderModal();
    const user = setupUser();
    await screen.findByText(t('upload.limit', { mb: 1 }));
    expect(await screen.findByLabelText(t('mode.plain'))).toBeChecked();
    await user.upload(screen.getByTestId('file-input'), pdf());
    expect(screen.getByText(t('upload.selected', { name: 'Báo cáo.pdf' }))).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(t('upload.language')), 'en');
    await user.click(screen.getByRole('button', { name: t('upload.submit') }));
    await vi.waitFor(() => expect(onUploaded).toHaveBeenCalledWith(item));
    const form = postedForm(calls);
    expect(form.get('language')).toBe('en');
    expect((form.get('file') as File).name).toBe('Báo cáo.pdf');
    expect(form.get('engine')).toBe('google_free');
    expect(form.get('model')).toBeNull();
  });

  it('defaults to AI mode with the saved model and sends engine and model', async () => {
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeChecked();
    expect(screen.getByLabelText(t('upload.model'))).toHaveValue('gemini-3.5-flash-lite');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(screen.getByRole('button', { name: t('upload.submit') }));
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('gemini');
    expect(form.get('model')).toBe('gemini-3.5-flash-lite');
  });

  it('greys out choices without a key and links to settings', async () => {
    mockApi(BASE);
    renderModal();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeDisabled();
    expect(screen.getByLabelText('Google Cloud Translation')).toBeDisabled();
    expect(screen.getByLabelText('Google miễn phí')).toBeChecked();
    expect(screen.getByRole('link', { name: t('upload.addKey') })).toHaveAttribute('href', '/settings/translation');
  });

  it('falls back to plain mode when the default engine has no usable key', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /api/settings': { body: settingsWith({ default_engine: 'gemini', default_model: 'gemini-3.8-flash' }) },
      'POST /api/files': { status: 202, body: fileItem() },
    });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('mode.plain'))).toBeChecked();
    expect(screen.getByLabelText(t('mode.ai'))).toBeDisabled();
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(screen.getByRole('button', { name: t('upload.submit') }));
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    expect(postedForm(calls).get('engine')).toBe('google_free');
  });

  it('lets the user switch to AI mode and pick another model', async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /api/settings': { body: settingsWith({
        engines: SETTINGS_WITH_GEMINI.engines, gemini_models: SETTINGS_WITH_GEMINI.gemini_models, credentials: SETTINGS_WITH_GEMINI.credentials,
      }) },
      'POST /api/files': { status: 202, body: fileItem() },
    });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('mode.plain'))).toBeChecked();
    await user.click(screen.getByLabelText(t('mode.ai')));
    await user.selectOptions(screen.getByLabelText(t('upload.model')), 'gemini-3.8-flash');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(screen.getByRole('button', { name: t('upload.submit') }));
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('gemini');
    expect(form.get('model')).toBe('gemini-3.8-flash');
  });

  it('switches to plain mode from an AI default and uploads with Google free, not the AI key', async () => {
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeChecked();
    await user.click(screen.getByLabelText(t('mode.plain')));
    expect(screen.getByLabelText('Google miễn phí')).toBeChecked();
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(screen.getByRole('button', { name: t('upload.submit') }));
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('google_free');
    expect(form.get('model')).toBeNull();
  });

  it('switches back to AI mode after plain and restores the previously chosen model', async () => {
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeChecked();
    await user.click(screen.getByLabelText(t('mode.plain')));
    await user.click(screen.getByLabelText(t('mode.ai')));
    expect(screen.getByLabelText(t('upload.model'))).toHaveValue('gemini-3.5-flash-lite');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(screen.getByRole('button', { name: t('upload.submit') }));
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('gemini');
    expect(form.get('model')).toBe('gemini-3.5-flash-lite');
  });

  it('still uploads when the settings request fails, explicitly with Google free', async () => {
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { status: 500 }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    await screen.findByText(t('upload.limit', { mb: 1 }));
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    expect(screen.queryByText(t('upload.mode'))).not.toBeInTheDocument();
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('google_free'); // không bao giờ để server âm thầm dùng mặc định (có thể là AI trả phí)
    expect(form.get('model')).toBeNull();
    expect(form.get('font')).toBeNull(); // không biết font mặc định → để server tự lấy (không trả phí)
    expect(screen.queryByLabelText(t('font.field'))).not.toBeInTheDocument();
  });

  it('sends the chosen translated-text font with the file', async () => {
    const { calls } = mockApi({ ...BASE, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    const select = await screen.findByLabelText(t('font.field'));
    expect(select).toHaveValue('auto');
    await user.selectOptions(select, 'serif');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    expect(postedForm(calls).get('font')).toBe('serif');
  });

  it('starts from the font saved in settings', async () => {
    const { calls } = mockApi({
      ...BASE, 'GET /api/settings': { body: settingsWith({ default_font: 'sans' }) }, 'POST /api/files': { status: 202, body: fileItem() },
    });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('font.field'))).toHaveValue('sans');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    expect(postedForm(calls).get('font')).toBe('sans');
  });

  it('keeps "Dịch" disabled until the settings request has settled', async () => {
    const { calls, fetchMock } = mockApi({ ...BASE, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI }, 'POST /api/files': { status: 202, body: fileItem() } });
    const answer = fetchMock.getMockImplementation()!;
    let release = () => {};
    const settled = new Promise<void>((resolve) => { release = resolve; });
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === '/api/settings') await settled;
      return answer(input, init);
    });
    renderModal();
    const user = setupUser();
    await screen.findByText(t('upload.limit', { mb: 1 }));
    await user.upload(screen.getByTestId('file-input'), pdf());
    const submit = screen.getByRole('button', { name: t('upload.submit') });
    expect(submit).toBeDisabled();
    release();
    expect(await screen.findByLabelText(t('mode.ai'))).toBeChecked();
    expect(submit).toBeEnabled();
    await user.click(submit);
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    expect(postedForm(calls).get('engine')).toBe('gemini');
  });

  it('accepts a dropped file', async () => {
    mockApi(BASE);
    renderModal();
    await screen.findByText(t('upload.limit', { mb: 1 }));
    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [pdf('keo-tha.pdf')] } });
    expect(screen.getByText(t('upload.selected', { name: 'keo-tha.pdf' }))).toBeInTheDocument();
  });

  it('opens with the file chosen on the home page already selected, and uploads it', async () => {
    const { calls } = mockApi({ ...BASE, 'POST /api/files': { status: 202, body: fileItem() } });
    const { onUploaded } = renderModal(pdf('tu-trang-chu.pdf'));
    expect(await screen.findByText(t('upload.selected', { name: 'tu-trang-chu.pdf' }))).toBeInTheDocument();
    await setupUser().click(await submitReady());
    await vi.waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect((postedForm(calls).get('file') as File).name).toBe('tu-trang-chu.pdf');
  });

  it('still lets the user replace a preselected file with the in-modal drop zone', async () => {
    mockApi(BASE);
    renderModal(pdf('dau.pdf'));
    await screen.findByText(t('upload.selected', { name: 'dau.pdf' }));
    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [pdf('sau.pdf')] } });
    expect(screen.getByText(t('upload.selected', { name: 'sau.pdf' }))).toBeInTheDocument();
  });

  it('rejects non-PDF and oversize files before uploading', async () => {
    const { calls } = mockApi(BASE);
    renderModal();
    const user = setupUser();
    await screen.findByText(t('upload.limit', { mb: 1 }));
    await user.upload(screen.getByTestId('file-input'), new File(['x'], 'ghi-chu.txt', { type: 'text/plain' }));
    expect(screen.getByText(t('error.not_pdf'))).toBeInTheDocument();
    await user.upload(screen.getByTestId('file-input'), pdf('to.pdf', 2 * 1024 * 1024));
    expect(screen.getByText(t('error.too_large', { mb: 1 }))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
  });

  it('asks for a file when none is chosen', async () => {
    mockApi(BASE);
    renderModal();
    await screen.findByRole('button', { name: t('upload.submit') });
    await setupUser().click(await submitReady());
    expect(screen.getByText(t('upload.needFile'))).toBeInTheDocument();
  });

  it('shows the server reason and lets the user try again', async () => {
    mockApi({ ...BASE, 'POST /api/files': { status: 429, body: { detail: { code: 'too_many_pending', limit: 3 } } } });
    renderModal();
    const user = setupUser();
    await user.upload(await screen.findByTestId('file-input'), pdf());
    await user.click(await submitReady());
    expect(await screen.findByText(t('error.too_many_pending', { limit: 3 }))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('upload.submit') })).toBeEnabled();
  });

  it('sends one request on a double click', async () => {
    const { calls } = mockApi({ ...BASE, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    await user.upload(await screen.findByTestId('file-input'), pdf());
    await user.dblClick(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
  });

  // jsdom không dàn trang nên không đo được nút có nằm trong khung nhìn hay không (bằng chứng thật là bài kiểm trên
  // trình duyệt 1280x720 / 1366x768 / 375x667 và E2E); test này chỉ giữ hai quy tắc CSS làm việc đó khỏi bị gỡ mất.
  it('scrolls the content area (not the title) and keeps Huỷ / Dịch in a row stuck to its bottom', async () => {
    mockApi(BASE);
    renderModal();
    const submit = await submitReady();
    expect(getComputedStyle(screen.getByRole('dialog')).overflowY).not.toBe('auto');
    expect(getComputedStyle(screen.getByTestId('modal-content')).overflowY).toBe('auto');
    const actions = screen.getByTestId('upload-actions');
    expect(getComputedStyle(actions).position).toBe('sticky');
    expect(actions).toContainElement(submit);
    expect(actions).toContainElement(screen.getByRole('button', { name: t('common.cancel') }));
  });
});
