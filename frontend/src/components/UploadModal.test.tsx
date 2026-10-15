import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetMetaCache } from '../files/useMeta';
import { t } from '../i18n/t';
import { STYLE_FIELDS, fieldLabel, styleOf } from '../files/profiles';
import { TRANSLATION_SETTINGS_CACHE_KEY } from '../api/settings';
import { cacheGet, cacheSet } from '../lib/swrCache';
import { META, MY_PROFILE, SEEDED_PROFILES, SETTINGS, SETTINGS_WITH_GEMINI, fileItem, settingsWith } from '../test/fixtures';
import { bodies, holdRequests, mockApi, type Call } from '../test/mockApi';
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
const postedForm = (calls: Call[]) => calls.find((call) => call.method === 'POST' && call.url === '/api/files')!.body as FormData;
const TECHNICAL = SEEDED_PROFILES[2];
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
  it('shows the advanced section in advanced mode with an AI engine and sends only the changed fields', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: 'preset:technical' });
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('upload.advanced.profile'))).toHaveValue('preset:technical');
    expect(screen.queryByLabelText(t('profiles.field.tone'))).not.toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    expect(screen.getByLabelText(t('profiles.field.terms'))).toHaveValue('keep'); // điền sẵn từ hồ sơ
    await user.selectOptions(screen.getByLabelText(t('profiles.field.tone')), 'friendly');
    await user.type(screen.getByLabelText(t('upload.advanced.context')), 'Tài liệu API nội bộ.');
    expect(screen.getByText(t('profiles.form.counter', { n: 'Tài liệu API nội bộ.'.length, max: 2000 }))).toBeInTheDocument();
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('gemini');
    expect(form.get('profile')).toBe('preset:technical');
    expect(JSON.parse(String(form.get('style')))).toEqual({ tone: 'friendly' });
    expect(form.get('context')).toBe('Tài liệu API nội bộ.');
  });

  it('names a refused field by its label, not the raw key', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true });
    mockApi({ ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/files': { status: 422, body: { detail: { code: 'invalid_style', field: 'context' } } } });
    renderModal();
    const user = setupUser();
    await user.type(await screen.findByLabelText(t('upload.advanced.context')), 'Ngữ cảnh');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    expect(await screen.findByText(t('error.invalid_style', { field: t('upload.advanced.context') }))).toBeInTheDocument();
    expect(screen.queryByText(/context/)).not.toBeInTheDocument();
  });

  it('hides the advanced section in plain mode and sends nothing advanced', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: 'preset:technical' });
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.click(screen.getByLabelText(t('mode.plain')));
    expect(screen.queryByTestId('upload-advanced')).not.toBeInTheDocument();
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('google_free');
    for (const key of ['profile', 'style', 'context']) expect(form.has(key)).toBe(false);
  });

  it('has no advanced section when advanced mode is off', async () => {
    mockApi({ ...BASE, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI } });
    renderModal();
    await screen.findByLabelText(t('mode.ai'));
    expect(screen.queryByText(t('upload.advanced.title'))).not.toBeInTheDocument();
  });

  it('has no advanced section without a Gemini key, even in advanced mode', async () => {
    mockApi({ ...BASE, 'GET /api/settings': { body: settingsWith({ advance_mode: true }) } });
    renderModal();
    await screen.findByLabelText(t('mode.plain'));
    expect(screen.queryByTestId('upload-advanced')).not.toBeInTheDocument();
    expect(screen.queryByText(t('upload.advanced.title'))).not.toBeInTheDocument();
  });

  it('sends no advanced keys at all when advanced mode is off, even with an AI engine', async () => {
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: SETTINGS_WITH_GEMINI }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('mode.ai'));
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('engine')).toBe('gemini');
    for (const key of ['profile', 'style', 'context']) expect(form.has(key)).toBe(false);
  });

  it('sends no advanced keys when advanced mode is on but nothing was chosen', async () => {
    const { calls } = mockApi({ ...BASE, 'GET /api/settings': { body: settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true }) }, 'POST /api/files': { status: 202, body: fileItem() } });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
    for (const key of ['profile', 'style', 'context']) expect(postedForm(calls).has(key)).toBe(false);
  });

  it('saves the customised fields into the selected profile and stops sending them as overrides', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: TECHNICAL.id, profiles: SEEDED_PROFILES });
    cacheSet(TRANSLATION_SETTINGS_CACHE_KEY, settings);
    const { calls } = mockApi({
      ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/files': { status: 202, body: fileItem() },
      [`PUT /api/profiles/${TECHNICAL.id}`]: { body: { ...TECHNICAL, tone: 'friendly' } },
    });
    renderModal();
    const user = setupUser();
    expect(await screen.findByLabelText(t('upload.advanced.profile'))).toHaveValue(TECHNICAL.id);
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    const saveName = t('profiles.saveInto', { name: 'Tài liệu kỹ thuật' });
    expect(screen.queryByRole('button', { name: saveName })).not.toBeInTheDocument(); // chưa khác hồ sơ
    await user.selectOptions(screen.getByLabelText(t('profiles.field.tone')), 'friendly');
    await user.click(screen.getByRole('button', { name: saveName }));
    await vi.waitFor(() => expect(bodies(calls, 'PUT', `/api/profiles/${TECHNICAL.id}`)).toEqual([{ name: 'Tài liệu kỹ thuật', ...styleOf(TECHNICAL), tone: 'friendly' }]));
    expect(await screen.findByText(t('profiles.savedInto', { name: 'Tài liệu kỹ thuật' }))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: saveName })).not.toBeInTheDocument(); // nay bằng hồ sơ
    expect(cacheGet(TRANSLATION_SETTINGS_CACHE_KEY)).toBeUndefined();
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/files')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('profile')).toBe(TECHNICAL.id);
    expect(form.has('style')).toBe(false); // giá trị đã là của hồ sơ → không còn ghi đè
  });

  it('freezes the advanced fields while a profile save is in flight, so the upload sends what the screen shows', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: TECHNICAL.id, profiles: SEEDED_PROFILES });
    const created = { ...TECHNICAL, id: 'p00000000002', name: 'Hợp đồng API', tone: 'friendly', audience: 'client', preset_slug: null };
    const { calls, fetchMock } = mockApi({
      ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/files': { status: 202, body: fileItem() },
      [`PUT /api/profiles/${TECHNICAL.id}`]: { body: { ...TECHNICAL, tone: 'friendly' } },
      'POST /api/profiles': { status: 201, body: created },
    });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    await user.selectOptions(screen.getByLabelText(t('profiles.field.tone')), 'friendly');
    const frozen = () => [
      screen.getByLabelText(t('upload.advanced.profile')), screen.getByRole('checkbox', { name: t('upload.advanced.customize') }),
      ...STYLE_FIELDS.map((field) => screen.getByLabelText(fieldLabel(field))), screen.getByLabelText(t('upload.advanced.context')),
    ];
    // Lưu vào hồ sơ: trong lúc chờ PUT không đổi được trường nào (đổi được thì lượt lưu xong sẽ ghi đè lên bằng giá trị lúc bấm).
    const putHeld = holdRequests(fetchMock, `/api/profiles/${TECHNICAL.id}`);
    const saveInto = screen.getByRole('button', { name: t('profiles.saveInto', { name: 'Tài liệu kỹ thuật' }) });
    await user.click(saveInto);
    await vi.waitFor(() => expect(saveInto).toBeDisabled()); // đang lưu
    for (const control of frozen()) expect(control).toBeDisabled();
    putHeld.release();
    expect(await screen.findByText(t('profiles.savedInto', { name: 'Tài liệu kỹ thuật' }))).toBeInTheDocument();
    for (const control of frozen()) expect(control).toBeEnabled();
    // Lưu thành hồ sơ mới: cũng vậy trong lúc chờ POST.
    await user.selectOptions(screen.getByLabelText(t('profiles.field.audience')), 'client');
    await user.click(screen.getByRole('button', { name: t('profiles.saveAsNew') }));
    fireEvent.change(screen.getByLabelText(t('profiles.form.name')), { target: { value: 'Hợp đồng API' } });
    const postHeld = holdRequests(fetchMock, '/api/profiles');
    const create = screen.getByRole('button', { name: t('profiles.create') });
    await user.click(create);
    await vi.waitFor(() => expect(create).toBeDisabled()); // đang lưu
    for (const control of frozen()) expect(control).toBeDisabled();
    postHeld.release();
    await vi.waitFor(() => expect(screen.getByLabelText(t('upload.advanced.profile'))).toHaveValue('p00000000002'));
    for (const control of frozen()) expect(control).toBeEnabled();
    // Sau khi lưu: đổi tiếp trên màn hình, rồi tải lên — thân gửi đi đúng như màn hình đang hiện.
    await user.selectOptions(screen.getByLabelText(t('profiles.field.numbers')), 'target_convention');
    fireEvent.change(screen.getByLabelText(t('upload.advanced.context')), { target: { value: 'Hợp đồng dịch vụ.' } });
    expect(screen.getByLabelText(t('profiles.field.tone'))).toHaveValue('friendly');
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/files')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('profile')).toBe('p00000000002');
    expect(JSON.parse(String(form.get('style')))).toEqual({ numbers: 'target_convention' });
    expect(form.get('context')).toBe('Hợp đồng dịch vụ.');
  });

  it('offers no save-into for a profile that is not one of my rows', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: 'preset:technical' });
    mockApi({ ...BASE, 'GET /api/settings': { body: settings } });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    await user.selectOptions(screen.getByLabelText(t('profiles.field.tone')), 'friendly');
    expect(screen.queryByRole('button', { name: /^Lưu vào hồ sơ/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('profiles.saveAsNew') })).toBeEnabled();
  });

  it('saves the customised fields as a new profile, selects it and never opens a second dialog', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: TECHNICAL.id, profiles: SEEDED_PROFILES });
    cacheSet(TRANSLATION_SETTINGS_CACHE_KEY, settings);
    const created = { ...TECHNICAL, id: 'p00000000002', name: 'Hợp đồng API', tone: 'friendly', preset_slug: null };
    const { calls } = mockApi({
      ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/files': { status: 202, body: fileItem() },
      'POST /api/profiles': { status: 201, body: created },
    });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    await user.selectOptions(screen.getByLabelText(t('profiles.field.tone')), 'friendly');
    await user.click(screen.getByRole('button', { name: t('profiles.saveAsNew') }));
    const name = screen.getByLabelText(t('profiles.form.name'));
    expect(name).toHaveValue(t('profiles.cloneName', { name: 'Tài liệu kỹ thuật' }));
    expect(screen.getAllByRole('dialog')).toHaveLength(1); // ô tên inline, không dialog lồng dialog
    fireEvent.change(name, { target: { value: 'Hợp đồng API' } });
    await user.click(screen.getByRole('button', { name: t('profiles.create') }));
    await vi.waitFor(() => expect(bodies(calls, 'POST', '/api/profiles')).toEqual([{ name: 'Hợp đồng API', ...styleOf(TECHNICAL), tone: 'friendly' }]));
    await vi.waitFor(() => expect(screen.getByLabelText(t('upload.advanced.profile'))).toHaveValue('p00000000002')); // chọn luôn hồ sơ mới
    expect(screen.queryByLabelText(t('profiles.form.name'))).not.toBeInTheDocument();
    expect(cacheGet(TRANSLATION_SETTINGS_CACHE_KEY)).toBeUndefined();
    await user.upload(screen.getByTestId('file-input'), pdf());
    await user.click(await submitReady());
    await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/files')).toHaveLength(1));
    const form = postedForm(calls);
    expect(form.get('profile')).toBe('p00000000002');
    expect(form.has('style')).toBe(false);
  });

  it('shows the server reason inline when saving as a new profile is refused', async () => {
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: TECHNICAL.id, profiles: SEEDED_PROFILES });
    mockApi({ ...BASE, 'GET /api/settings': { body: settings }, 'POST /api/profiles': { status: 409, body: { detail: { code: 'too_many_profiles', limit: 20 } } } });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    await user.click(screen.getByRole('button', { name: t('profiles.saveAsNew') }));
    await user.click(screen.getByRole('button', { name: t('profiles.create') }));
    expect(await screen.findByText(t('error.too_many_profiles', { limit: 20 }))).toBeInTheDocument();
    expect(screen.getByLabelText(t('upload.advanced.profile'))).toHaveValue(TECHNICAL.id); // không đổi hồ sơ đang chọn
  });

  it('disables "save as a new profile" when the 20 own profiles are used up', async () => {
    const twenty = Array.from({ length: 20 }, (_, index) => ({ ...MY_PROFILE, id: `p${String(index + 10).padStart(11, '0')}`, name: `Hồ sơ ${index + 1}` }));
    const settings = settingsWith({ ...SETTINGS_WITH_GEMINI, advance_mode: true, default_profile: twenty[0].id, profiles: twenty });
    mockApi({ ...BASE, 'GET /api/settings': { body: settings } });
    renderModal();
    const user = setupUser();
    await screen.findByLabelText(t('upload.advanced.profile'));
    await user.click(screen.getByRole('checkbox', { name: t('upload.advanced.customize') }));
    expect(screen.getByRole('button', { name: t('profiles.saveAsNew') })).toBeDisabled();
  });
});
