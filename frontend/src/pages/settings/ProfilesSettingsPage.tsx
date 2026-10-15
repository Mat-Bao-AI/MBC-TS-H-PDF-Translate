import { useCallback, useEffect, useState, type ComponentProps } from 'react';
import { Alert, Badge, Box, Card, Dialog, FillButton, FlexBox, StrokeButton, Text } from '@codecademy/gamut';
import { toApiError, type ApiError } from '../../api/client';
import { profilesApi } from '../../api/profiles';
import { TRANSLATION_SETTINGS_CACHE_KEY, settingsApi, type ProfileBody, type ProfileItem, type SettingsInfo, type StyleValues } from '../../api/settings';
import { ProfileFormFields } from '../../components/ProfileFormFields';
import { SkeletonCard } from '../../components/SkeletonCard';
import { STYLE_DEFAULTS, cloneName, isFromPreset, styleOf, valueLabel } from '../../files/profiles';
import { errorText, t } from '../../i18n/t';
import { cacheGet, cacheSet } from '../../lib/swrCache';

const CACHE_KEY = TRANSLATION_SETTINGS_CACHE_KEY; // cùng bộ nhớ đệm với tab Dịch thuật: cả hai đọc GET /api/settings
const SKELETON_HEIGHT = 520;
type ConfirmCta = ComponentProps<typeof Dialog>['confirmCta'];
type Editing = { title: string; id: string | null; initial: StyleValues & { name: string } };

/** "Cân bằng · Chuyên nghiệp · Chuyên gia · Giữ nguyên tiếng gốc" — bốn trường đầu, đủ để nhận ra hồ sơ. */
const summary = (profile: ProfileItem) =>
  [valueLabel('fidelity', profile.fidelity), valueLabel('tone', profile.tone), valueLabel('audience', profile.audience), valueLabel('terms', profile.terms)].join(' · ');

function ProfileRow({ profile, isDefault, busy, canClone, onEdit, onClone, onDelete, onDefault }: {
  profile: ProfileItem; isDefault: boolean; busy: boolean; canClone: boolean;
  onEdit: () => void; onClone: () => void; onDelete: () => void; onDefault: () => void;
}) {
  const custom = profile.kind === 'custom'; // mẫu trong code (người chưa gieo) chỉ đọc — bình thường không còn thấy ở tab này
  return (
    <Card p={16} data-testid={`profile-${profile.id}`}>
      <FlexBox justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={12}>
        <Box minWidth={0}>
          <FlexBox gap={8} alignItems="center" flexWrap="wrap">
            <Text fontWeight="title">{profile.name}</Text>
            {!custom && <Badge variant="tertiary" size="sm">{t('profiles.preset')}</Badge>}
            {isFromPreset(profile) && <Badge variant="tertiary" size="sm">{t('profiles.fromPreset')}</Badge>}
            {isDefault && <Badge variant="primary" size="sm">{t('profiles.default')}</Badge>}
          </FlexBox>
          <Text fontSize={14} color="text-secondary">{summary(profile)}</Text>
        </Box>
        <FlexBox gap={8} flexWrap="wrap">
          {custom && <StrokeButton type="button" size="small" onClick={onEdit} disabled={busy}>{t('profiles.action.edit')}</StrokeButton>}
          <StrokeButton type="button" size="small" onClick={onClone} disabled={busy || !canClone}>{t('profiles.action.clone')}</StrokeButton>
          <StrokeButton type="button" size="small" onClick={onDefault} disabled={busy}>
            {isDefault ? t('profiles.action.unsetDefault') : t('profiles.action.setDefault')}
          </StrokeButton>
          {custom && <StrokeButton type="button" size="small" onClick={onDelete} disabled={busy}>{t('profiles.action.delete')}</StrokeButton>}
        </FlexBox>
      </FlexBox>
    </Card>
  );
}

/** Form hồ sơ trong Dialog. Gamut gọi onRequestClose TRƯỚC onClick của nút xác nhận: hộp đóng, trang cha gửi request và báo kết quả
 *  trên trang (như RetranslateDialog). Trường dùng chung với form tại chỗ ở Cài đặt › Dịch thuật (ProfileFormFields). */
function ProfileForm({ editing, onSubmit, onCancel }: { editing: Editing; onSubmit: (body: ProfileBody) => void; onCancel: () => void }) {
  const [name, setName] = useState(editing.initial.name);
  const [style, setStyle] = useState<StyleValues>(() => {
    const { name: _name, ...rest } = editing.initial;
    return rest;
  });
  const confirmCta = { children: t('profiles.form.save'), onClick: () => onSubmit({ name, ...style }), disabled: name.trim() === '' } as ConfirmCta;
  return (
    <Dialog isOpen title={editing.title} size="medium" onRequestClose={onCancel} confirmCta={confirmCta}
      cancelCta={{ children: t('common.cancel'), onClick: onCancel }}>
      <ProfileFormFields idPrefix="profile" name={name} style={style} onNameChange={setName} onStyleChange={setStyle} />
    </Dialog>
  );
}

/** Cài đặt › Hồ sơ dịch (chỉ khi Chế độ nâng cao bật — AdvanceOnly ở route). Một danh sách "Hồ sơ của tôi" (spec 2026-10-15 §5, §9):
 *  5 dòng gieo từ mẫu mang nhãn "Từ mẫu", sửa/xoá như mọi hồ sơ; "Khôi phục 5 mẫu gốc" đưa chúng về gốc / tạo lại. */
export function ProfilesSettingsPage() {
  const [settings, setSettings] = useState<SettingsInfo | null>(() => cacheGet<SettingsInfo>(CACHE_KEY) ?? null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [deleting, setDeleting] = useState<ProfileItem | null>(null);
  const [restoringPresets, setRestoringPresets] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback((next: SettingsInfo) => { cacheSet(CACHE_KEY, next); setSettings(next); }, []);
  const load = useCallback(() => {
    setLoadError(null);
    settingsApi.get().then(apply).catch((caught) => setLoadError(toApiError(caught)));
  }, [apply]);
  useEffect(() => { load(); }, [load]);

  async function run(action: () => Promise<string>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const done = await action();
      apply(await settingsApi.get()); // danh sách + hồ sơ mặc định theo server
      setNotice(done);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  const submit = (id: string | null, body: ProfileBody) => run(async () => {
    if (id) await profilesApi.update(id, body);
    else await profilesApi.create(body);
    return t('profiles.saved');
  });
  const remove = (profile: ProfileItem) => run(async () => {
    await profilesApi.remove(profile.id);
    return t('profiles.deleted');
  });
  const setDefault = (current: SettingsInfo, id: string | null) => run(async () => {
    await settingsApi.savePreferences({
      default_engine: current.default_engine, default_model: current.default_model, default_font: current.default_font, default_profile: id,
    });
    return t('profiles.defaultSaved');
  });
  const restorePresets = () => run(async () => {
    await profilesApi.restorePresets();
    return t('profiles.restoredPresets');
  });

  if (loadError) {
    return <Alert type="error" placement="inline" cta={{ text: t('common.retry'), onClick: load }}>{t('settings.loadError')}</Alert>;
  }
  if (!settings) return <SkeletonCard height={SKELETON_HEIGHT} />;

  const mine = settings.profiles.filter((profile) => profile.kind === 'custom');
  const full = mine.length >= settings.profile_limit;
  const openCreate = () => setEditing({ title: t('profiles.form.createTitle'), id: null, initial: { name: '', ...STYLE_DEFAULTS } });
  const openClone = (profile: ProfileItem) =>
    setEditing({ title: t('profiles.form.createTitle'), id: null, initial: { name: cloneName(profile.name), ...styleOf(profile) } });
  const openEdit = (profile: ProfileItem) =>
    setEditing({ title: t('profiles.form.editTitle', { name: profile.name }), id: profile.id, initial: { name: profile.name, ...styleOf(profile) } });
  const rowProps = (profile: ProfileItem) => ({
    profile, busy, canClone: !full, isDefault: settings.default_profile === profile.id,
    onEdit: () => openEdit(profile), onClone: () => openClone(profile), onDelete: () => setDeleting(profile),
    onDefault: () => void setDefault(settings, settings.default_profile === profile.id ? null : profile.id),
  });

  return (
    <Box>
      <Text fontSize={14} color="text-secondary">{t('profiles.intro')}</Text>
      {error && <Box mt={16}><Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert></Box>}
      {notice && <Box mt={16}><Alert type="success" placement="inline">{notice}</Alert></Box>}
      <FlexBox justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={12} mt={24}>
        <Text as="h2" variant="title-sm">{t('profiles.title.mine')}</Text>
        <FlexBox gap={12} alignItems="center" flexWrap="wrap">
          <Text fontSize={14} color="text-secondary">{t('profiles.count', { n: mine.length, limit: settings.profile_limit })}</Text>
          <StrokeButton type="button" size="small" onClick={() => setRestoringPresets(true)} disabled={busy}>{t('profiles.restorePresets')}</StrokeButton>
          <FillButton type="button" size="small" onClick={openCreate} disabled={busy || full}>{t('profiles.action.new')}</FillButton>
        </FlexBox>
      </FlexBox>
      {full && <Box mt={12}><Alert type="notice" placement="inline">{t('profiles.limitReached', { limit: settings.profile_limit })}</Alert></Box>}
      <FlexBox flexDirection="column" gap={12} mt={12}>
        {settings.profiles.length === 0 && <Text fontSize={14} color="text-secondary">{t('profiles.empty')}</Text>}
        {settings.profiles.map((profile) => <ProfileRow key={profile.id} {...rowProps(profile)} />)}
      </FlexBox>
      {editing && (
        <ProfileForm key={editing.id ?? editing.initial.name} editing={editing}
          onSubmit={(body) => { const id = editing.id; setEditing(null); void submit(id, body); }}
          onCancel={() => setEditing(null)} />
      )}
      <Dialog isOpen={deleting !== null} title={t('profiles.deleteTitle')} variant="danger" onRequestClose={() => setDeleting(null)}
        confirmCta={{ children: t('profiles.action.delete'), onClick: () => { const target = deleting; setDeleting(null); if (target) void remove(target); } }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setDeleting(null) }}>
        {deleting ? t('profiles.deleteBody', { name: deleting.name }) : ''}
      </Dialog>
      <Dialog isOpen={restoringPresets} title={t('profiles.restorePresetsTitle')} onRequestClose={() => setRestoringPresets(false)}
        confirmCta={{ children: t('profiles.restorePresets'), onClick: () => { setRestoringPresets(false); void restorePresets(); } }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setRestoringPresets(false) }}>
        {t('profiles.restorePresetsBody')}
      </Dialog>
    </Box>
  );
}
