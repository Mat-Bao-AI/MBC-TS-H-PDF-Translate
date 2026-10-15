import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { AdvanceOnly, RequireAuth } from '../../auth/RequireAuth';
import { AppShell } from '../../components/AppShell';
import { resetMetaCache } from '../../files/useMeta';
import { styleOf } from '../../files/profiles';
import { t } from '../../i18n/t';
import { META, MY_PROFILE, SEEDED_PROFILES, settingsWith, signedInAs } from '../../test/fixtures';
import { bodies, holdRequests, mockApi, sequence } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { SettingsLayout } from './SettingsLayout';
import { ProfilesSettingsPage } from './ProfilesSettingsPage';

const QUICK = SEEDED_PROFILES[0];
const TECHNICAL = SEEDED_PROFILES[2];
const ON = settingsWith({ advance_mode: true, profiles: [...SEEDED_PROFILES, MY_PROFILE] });
const BASE = { ...signedInAs({ advance_mode: true }), 'GET /api/meta': { body: META }, 'GET /api/settings': { body: ON } };
const row = (id: string) => within(screen.getByTestId(`profile-${id}`));

function renderProfiles(at = '/settings/profiles') {
  return renderApp(
    <Routes>
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="translation" element={<p>thẻ dịch thuật</p>} />
          <Route path="profiles" element={<AdvanceOnly><ProfilesSettingsPage /></AdvanceOnly>} />
        </Route>
      </Route>
    </Routes>,
    { at },
  );
}

beforeEach(() => resetMetaCache());

describe('ProfilesSettingsPage', () => {
  it('lists every profile in one list, marks the five seeded from presets and lets all of them be edited or deleted', async () => {
    mockApi(BASE);
    renderProfiles();
    expect(await screen.findByRole('heading', { name: t('profiles.title.mine') })).toBeInTheDocument();
    expect(screen.queryByText(t('profiles.preset'))).not.toBeInTheDocument(); // không còn nhóm "Hồ sơ mẫu" chỉ đọc
    for (const profile of SEEDED_PROFILES) {
      expect(row(profile.id).getByText(profile.name)).toBeInTheDocument();
      expect(row(profile.id).getByText(t('profiles.fromPreset'))).toBeInTheDocument();
      expect(row(profile.id).getByRole('button', { name: t('profiles.action.edit') })).toBeInTheDocument();
      expect(row(profile.id).getByRole('button', { name: t('profiles.action.delete') })).toBeInTheDocument();
    }
    expect(row(MY_PROFILE.id).queryByText(t('profiles.fromPreset'))).not.toBeInTheDocument();
    expect(screen.getByText(t('profiles.count', { n: 6, limit: 20 }))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('profiles.restorePresets') })).toBeInTheDocument();
  });

  it('clones a seeded profile into a prefilled form and posts the copy', async () => {
    const { calls } = mockApi({ ...BASE, 'POST /api/profiles': { status: 201, body: { ...MY_PROFILE, id: 'p00000000002' } } });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByTestId(`profile-${TECHNICAL.id}`)).findByRole('button', { name: t('profiles.action.clone') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByLabelText(t('profiles.form.name'))).toHaveValue(t('profiles.cloneName', { name: 'Tài liệu kỹ thuật' }));
    expect(dialog.getByLabelText(t('profiles.field.terms'))).toHaveValue('keep');
    expect(dialog.getByLabelText(t('profiles.field.custom_instructions'))).toHaveValue(TECHNICAL.custom_instructions);
    expect(dialog.getByText(t('profiles.form.counter', { n: TECHNICAL.custom_instructions.length, max: 1000 }))).toBeInTheDocument();
    await user.selectOptions(dialog.getByLabelText(t('profiles.field.tone')), 'friendly');
    await user.click(dialog.getByRole('button', { name: t('profiles.form.save') }));
    await waitFor(() => expect(bodies(calls, 'POST', '/api/profiles')).toEqual([
      { name: t('profiles.cloneName', { name: 'Tài liệu kỹ thuật' }), ...styleOf(TECHNICAL), tone: 'friendly' },
    ]));
    expect(await screen.findByText(t('profiles.saved'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'GET' && call.url === '/api/settings').length).toBeGreaterThanOrEqual(2); // nạp lại danh sách
  });

  it('shortens the copy name of a 60-character profile so the copy stays within the limit', async () => {
    const longName = 'Hồ sơ hợp đồng thuê văn phòng giữa hai công ty, bản dài 60kt';
    expect([...longName]).toHaveLength(60);
    const long = { ...MY_PROFILE, name: longName };
    const { calls } = mockApi({
      ...BASE, 'GET /api/settings': { body: settingsWith({ ...ON, profiles: [...SEEDED_PROFILES, long] }) },
      'POST /api/profiles': { status: 201, body: { ...long, id: 'p00000000002' } },
    });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByTestId(`profile-${MY_PROFILE.id}`)).findByRole('button', { name: t('profiles.action.clone') }));
    const dialog = within(await screen.findByRole('dialog'));
    const name = dialog.getByLabelText(t('profiles.form.name')) as HTMLInputElement;
    expect([...name.value]).toHaveLength(60);
    expect(name.value.endsWith(t('profiles.cloneName', { name: '' }))).toBe(true);
    await user.click(dialog.getByRole('button', { name: t('profiles.form.save') }));
    await waitFor(() => expect(bodies(calls, 'POST', '/api/profiles')).toHaveLength(1));
    expect([...bodies(calls, 'POST', '/api/profiles')[0].name].length).toBeLessThanOrEqual(60);
  });

  it('edits a seeded profile through the same form and sends the whole body to PUT', async () => {
    const { calls } = mockApi({ ...BASE, [`PUT /api/profiles/${TECHNICAL.id}`]: { body: { ...TECHNICAL, name: 'Kỹ thuật B2B' } } });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByTestId(`profile-${TECHNICAL.id}`)).findByRole('button', { name: t('profiles.action.edit') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('profiles.form.editTitle', { name: 'Tài liệu kỹ thuật' }))).toBeInTheDocument();
    await user.clear(dialog.getByLabelText(t('profiles.form.name')));
    await user.type(dialog.getByLabelText(t('profiles.form.name')), 'Kỹ thuật B2B');
    await user.click(dialog.getByRole('button', { name: t('profiles.form.save') }));
    await waitFor(() => expect(bodies(calls, 'PUT', `/api/profiles/${TECHNICAL.id}`)).toEqual([{ ...styleOf(TECHNICAL), name: 'Kỹ thuật B2B' }]));
  });

  it('deletes my profile after a confirmation', async () => {
    const { calls } = mockApi({ ...BASE, [`DELETE /api/profiles/${MY_PROFILE.id}`]: { status: 204 } });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByTestId(`profile-${MY_PROFILE.id}`)).findByRole('button', { name: t('profiles.action.delete') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('profiles.deleteBody', { name: 'Hợp đồng' }))).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: t('profiles.action.delete') }));
    await waitFor(() => expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1));
    expect(await screen.findByText(t('profiles.deleted'))).toBeInTheDocument();
  });

  it('sets and unsets the default profile through preferences', async () => {
    const { calls } = mockApi({
      ...BASE,
      // run() nạp lại GET /api/settings sau mỗi thao tác: lần 1 (tải trang) chưa có mặc định, lần 2 (sau Đặt) có, lần 3 (sau Bỏ) hết.
      'GET /api/settings': sequence({ body: ON }, { body: settingsWith({ ...ON, default_profile: QUICK.id }) }, { body: ON }),
      'PUT /api/settings/preferences': { body: settingsWith({ ...ON, default_profile: QUICK.id }) },
    });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByTestId(`profile-${QUICK.id}`)).findByRole('button', { name: t('profiles.action.setDefault') }));
    await waitFor(() => expect(bodies(calls, 'PUT', '/api/settings/preferences')).toEqual([
      { default_engine: 'google_free', default_model: null, default_font: 'auto', default_profile: QUICK.id },
    ]));
    expect(await screen.findByText(t('profiles.defaultSaved'))).toBeInTheDocument();
    expect(row(QUICK.id).getByText(t('profiles.default'))).toBeInTheDocument();
    await user.click(row(QUICK.id).getByRole('button', { name: t('profiles.action.unsetDefault') }));
    await waitFor(() => expect(bodies(calls, 'PUT', '/api/settings/preferences')).toHaveLength(2));
    expect(bodies(calls, 'PUT', '/api/settings/preferences')[1].default_profile).toBeNull();
  });

  it('shows the default badge and the unset action on the current default', async () => {
    mockApi({ ...BASE, 'GET /api/settings': { body: settingsWith({ ...ON, default_profile: MY_PROFILE.id }) } });
    renderProfiles();
    const mine = within(await screen.findByTestId(`profile-${MY_PROFILE.id}`));
    expect(mine.getByText(t('profiles.default'))).toBeInTheDocument();
    expect(mine.getByRole('button', { name: t('profiles.action.unsetDefault') })).toBeInTheDocument();
    expect(row(QUICK.id).queryByText(t('profiles.default'))).not.toBeInTheDocument();
  });

  it('blocks creating or cloning at the limit and says why', async () => {
    const rest = Array.from({ length: 15 }, (_, index) => ({ ...MY_PROFILE, id: `p${String(index).padStart(11, '0')}`, name: `HS ${index}` }));
    mockApi({ ...BASE, 'GET /api/settings': { body: settingsWith({ ...ON, profiles: [...SEEDED_PROFILES, ...rest] }) } });
    renderProfiles();
    expect(await screen.findByText(t('profiles.limitReached', { limit: 20 }))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('profiles.action.new') })).toBeDisabled();
    expect(row(QUICK.id).getByRole('button', { name: t('profiles.action.clone') })).toBeDisabled();
  });

  it('shows a server validation error on the page, naming the field by its label', async () => {
    mockApi({ ...BASE, 'POST /api/profiles': { status: 422, body: { detail: { code: 'invalid_profile', field: 'name' } } } });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('profiles.action.new') }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.type(dialog.getByLabelText(t('profiles.form.name')), 'x');
    await user.click(dialog.getByRole('button', { name: t('profiles.form.save') }));
    expect(await screen.findByText(t('error.invalid_profile', { field: t('profiles.form.name') }))).toBeInTheDocument();
  });

  it('restores the five presets after a confirmation and reloads the list', async () => {
    const { calls } = mockApi({ ...BASE, 'POST /api/profiles/restore-presets': { body: { updated: 4, created: 1 } } });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('profiles.restorePresets') }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText(t('profiles.restorePresetsBody'))).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: t('profiles.restorePresets') }));
    await waitFor(() => expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles/restore-presets')).toHaveLength(1));
    expect(await screen.findByText(t('profiles.restoredPresets'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'GET' && call.url === '/api/settings').length).toBeGreaterThanOrEqual(2);
  });

  it('says when there is no room to recreate the presets', async () => {
    mockApi({ ...BASE, 'POST /api/profiles/restore-presets': { status: 409, body: { detail: { code: 'too_many_profiles', limit: 20 } } } });
    renderProfiles();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: t('profiles.restorePresets') }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('profiles.restorePresets') }));
    // Câu riêng cho "không đủ chỗ thêm mẫu" — "Bạn đã có 20 hồ sơ" là sai với người có 16–19 hồ sơ.
    expect(await screen.findByText(t('error.presets_no_room', { limit: 20 }))).toBeInTheDocument();
    expect(screen.queryByText(t('error.too_many_profiles', { limit: 20 }))).not.toBeInTheDocument();
  });

  it('disables the restore button while its request is pending so it cannot be submitted twice', async () => {
    const { calls, fetchMock } = mockApi({ ...BASE, 'POST /api/profiles/restore-presets': { body: { updated: 5, created: 0 } } });
    renderProfiles();
    const user = userEvent.setup();
    const open = await screen.findByRole('button', { name: t('profiles.restorePresets') });
    const { release } = holdRequests(fetchMock, '/api/profiles/restore-presets');
    await user.click(open);
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('profiles.restorePresets') }));
    await waitFor(() => expect(screen.getByRole('button', { name: t('profiles.restorePresets') })).toBeDisabled());
    release();
    expect(await screen.findByText(t('profiles.restoredPresets'))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/profiles/restore-presets')).toHaveLength(1);
  });
});
