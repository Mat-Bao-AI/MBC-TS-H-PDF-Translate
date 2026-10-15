import { useState } from 'react';
import { Alert, Box, FillButton, FlexBox, FormGroup, Input, Select, StrokeButton, Text, TextArea, Toggle } from '@codecademy/gamut';
import { toApiError, type ApiError } from '../api/client';
import type { AdvancedChoice, Snapshot } from '../api/files';
import { profilesApi } from '../api/profiles';
import { TRANSLATION_SETTINGS_CACHE_KEY, type ProfileItem, type SettingsInfo, type StyleField, type StyleValues } from '../api/settings';
import {
  CONTEXT_MAX, CUSTOM_MAX, ENUM_FIELDS, NAME_MAX, STYLE_DEFAULTS, cloneName, fieldLabel, findProfile, overridesAgainst, pickFields,
  profileOptions, styleOf, valueOptions,
} from '../files/profiles';
import { errorText, t } from '../i18n/t';
import { cacheClear } from '../lib/swrCache';

/** Trạng thái mục "Nâng cao" (spec 2026-10-14 §8). `touched` = trường người dùng đã chạm — là thứ được gửi khi không có hồ sơ. */
export type AdvancedState = { profile: string | null; custom: boolean; style: StyleValues; touched: Set<StyleField>; context: string };

const fromProfile = (profile: ProfileItem | null): AdvancedState =>
  ({ profile: profile?.id ?? null, custom: false, style: profile ? styleOf(profile) : STYLE_DEFAULTS, touched: new Set(), context: '' });

/** Khởi tạo (spec 2026-10-14 §8). `snapshot`:
 *  - bỏ trống = hộp tải lên → chọn sẵn hồ sơ mặc định;
 *  - null = dịch lại tệp cơ bản (không snapshot) → "Không áp", KHÔNG theo hồ sơ mặc định;
 *  - có, hồ sơ còn → giá trị HIỆN TẠI của hồ sơ ⊕ đúng các trường trong `overrides` (giá trị lấy từ snapshot), "Tuỳ chỉnh" bật khi có
 *    ghi đè — hồ sơ đã sửa sau lượt dịch thì bản sửa được áp; tham chiếu `preset:<slug>` cũ ánh xạ sang dòng gieo (findProfile);
 *  - có, hồ sơ đã mất → "Không áp" và mọi trường style của snapshot thành ghi đè (giữ đúng cấu hình đã lưu). */
export function initialAdvanced(settings: SettingsInfo, snapshot?: Snapshot | null): AdvancedState {
  if (snapshot === undefined) return fromProfile(findProfile(settings.profiles, settings.default_profile));
  if (snapshot === null) return fromProfile(null);
  const saved = snapshot.style ?? {};
  const context = snapshot.document_context ?? '';
  const profile = findProfile(settings.profiles, snapshot.profile?.id);
  if (profile) {
    const overridden = snapshot.overrides.filter((field) => saved[field] !== undefined);
    const style: StyleValues = { ...styleOf(profile), ...pickFields({ ...STYLE_DEFAULTS, ...saved }, overridden) };
    return { profile: profile.id, custom: overridden.length > 0, style, touched: new Set(overridden), context };
  }
  const touched = new Set<StyleField>(Object.keys(saved) as StyleField[]);
  return { profile: null, custom: touched.size > 0, style: { ...STYLE_DEFAULTS, ...saved }, touched, context };
}

/** Thân gửi lên server; null = không có gì nâng cao (server lưu config NULL). Có hồ sơ: chỉ trường khác hồ sơ; không: chỉ trường đã chạm. */
export function toAdvancedChoice(state: AdvancedState, settings: SettingsInfo): AdvancedChoice | null {
  const profile = findProfile(settings.profiles, state.profile);
  const style: Partial<StyleValues> = state.custom
    ? (profile ? overridesAgainst(styleOf(profile), state.style) : pickFields(state.style, state.touched))
    : {};
  const context = state.context.trim();
  const hasStyle = Object.keys(style).length > 0;
  if (!profile && !hasStyle && !context) return null;
  return { profile: profile?.id ?? null, style: hasStyle ? style : null, context: context || null };
}

type Props = {
  /** Tiền tố id: 'upload' | 'retranslate'. */
  idPrefix: string;
  settings: SettingsInfo;
  value: AdvancedState;
  onChange: (next: AdvancedState) => void;
  /** Hồ sơ vừa được lưu/tạo ngay trong hộp: cha thay `settings.profiles` (ô chọn hồ sơ đọc từ đó). */
  onProfilesChange: (profiles: ProfileItem[]) => void;
};

/** Mục "Nâng cao" dùng chung cho hộp tải lên và hộp dịch lại đơn (spec 2026-10-14 §8; 2026-10-15 §9). Cha CHỈ render khi động cơ đang
 *  chọn là AI (động cơ thuần → không có mục này, spec 2026-10-15 §6). Trong "Tuỳ chỉnh cho tài liệu này": "Lưu vào hồ sơ «X»" ghi 9 giá
 *  trị hiện tại vào hồ sơ riêng đang chọn (chỉ khi có khác biệt), "Lưu thành hồ sơ mới" tạo bằng ô tên inline (không dialog lồng dialog)
 *  rồi chọn luôn. Trong lúc lưu mọi ô của mục bị khoá: lượt lưu xong ghi lại trạng thái từ giá trị lúc bấm, nên một thay đổi xen giữa sẽ
 *  bị đè trong state trong khi ô chọn (uncontrolled) vẫn hiện lựa chọn mới — lượt dịch trả phí sẽ gửi khác với màn hình. */
export function AdvancedFields({ idPrefix, settings, value, onChange, onProfilesChange }: Props) {
  const [saving, setSaving] = useState(false);
  const [naming, setNaming] = useState(false);
  const [newName, setNewName] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const profile = findProfile(settings.profiles, value.profile);
  const dirty = profile ? Object.keys(overridesAgainst(styleOf(profile), value.style)).length > 0 : false;
  const full = settings.profiles.filter((candidate) => candidate.kind === 'custom').length >= settings.profile_limit;
  const pickProfile = (id: string) => {
    const next = findProfile(settings.profiles, id || null);
    // Đổi hồ sơ: điền lại 9 trường từ hồ sơ mới và bỏ các ghi đè cũ.
    onChange({ ...value, profile: next?.id ?? null, style: next ? styleOf(next) : STYLE_DEFAULTS, touched: new Set() });
    setNotice(null);
    setSaveError(null);
  };
  const setField = (field: StyleField, fieldValue: string) =>
    onChange({ ...value, style: { ...value.style, [field]: fieldValue }, touched: new Set([...value.touched, field]) });

  async function saveInto() {
    if (!profile || saving) return;
    setSaving(true);
    setNotice(null);
    setSaveError(null);
    try {
      const saved = await profilesApi.update(profile.id, { name: profile.name, ...value.style });
      onProfilesChange(settings.profiles.map((candidate) => (candidate.id === saved.id ? saved : candidate)));
      onChange({ ...value, touched: new Set() }); // giá trị nay là của hồ sơ: không còn gì để ghi đè
      cacheClear(TRANSLATION_SETTINGS_CACHE_KEY); // trang Cài đặt không hiện danh sách cũ
      setNotice(t('profiles.savedInto', { name: saved.name }));
    } catch (caught) {
      setSaveError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  async function saveAsNew() {
    const name = newName.trim();
    if (!name || saving) return;
    setSaving(true);
    setNotice(null);
    setSaveError(null);
    try {
      const created = await profilesApi.create({ name, ...value.style });
      onProfilesChange([...settings.profiles, created]);
      onChange({ ...value, profile: created.id, touched: new Set() }); // chọn luôn hồ sơ mới; giá trị đang có chính là của nó
      cacheClear(TRANSLATION_SETTINGS_CACHE_KEY);
      setNaming(false);
      setNotice(t('profiles.saved'));
    } catch (caught) {
      setSaveError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  const openNaming = () => {
    setNewName(profile ? cloneName(profile.name) : '');
    setNotice(null);
    setSaveError(null);
    setNaming(true);
  };

  return (
    <Box data-testid={`${idPrefix}-advanced`}>
      <Text as="p" fontWeight="title" mb={8}>{t('upload.advanced.title')}</Text>
      <FlexBox flexDirection="column" gap={12}>
        <FormGroup label={t('upload.advanced.profile')} htmlFor={`${idPrefix}-profile`} isSoloField>
          {/* Select của Gamut là uncontrolled: key theo hồ sơ để remount với defaultValue đúng (cả khi vừa tạo hồ sơ mới). */}
          <Select key={`${idPrefix}-profile-${value.profile ?? ''}-${settings.profiles.length}`} id={`${idPrefix}-profile`} defaultValue={value.profile ?? ''}
            options={profileOptions(settings.profiles)} onChange={(event) => pickProfile(event.target.value)} disabled={saving} />
        </FormGroup>
        <Toggle as="input" label={t('upload.advanced.customize')} checked={value.custom} disabled={saving}
          onChange={() => onChange({ ...value, custom: !value.custom })} />
        {value.custom && (
          <FlexBox flexDirection="column" gap={12} data-testid={`${idPrefix}-advanced-fields`}>
            {ENUM_FIELDS.map((field) => (
              <FormGroup key={field} label={fieldLabel(field)} htmlFor={`${idPrefix}-${field}`} isSoloField>
                <Select key={`${idPrefix}-${field}-${value.profile ?? ''}`} id={`${idPrefix}-${field}`} defaultValue={value.style[field]}
                  options={valueOptions(field)} onChange={(event) => setField(field, event.target.value)} disabled={saving} />
              </FormGroup>
            ))}
            <FormGroup label={fieldLabel('custom_instructions')} htmlFor={`${idPrefix}-custom_instructions`} isSoloField
              description={t('profiles.form.counter', { n: value.style.custom_instructions.length, max: CUSTOM_MAX })}>
              <TextArea id={`${idPrefix}-custom_instructions`} rows={3} value={value.style.custom_instructions} maxLength={CUSTOM_MAX}
                onChange={(event) => setField('custom_instructions', event.target.value)} disabled={saving} />
            </FormGroup>
            <FlexBox gap={8} flexWrap="wrap" alignItems="center">
              {profile && profile.kind === 'custom' && dirty && (
                <StrokeButton type="button" size="small" onClick={() => void saveInto()} disabled={saving}>
                  {t('profiles.saveInto', { name: profile.name })}
                </StrokeButton>
              )}
              {!naming && (
                <StrokeButton type="button" size="small" onClick={openNaming} disabled={saving || full}>{t('profiles.saveAsNew')}</StrokeButton>
              )}
            </FlexBox>
            {naming && (
              <FlexBox gap={8} flexWrap="wrap" alignItems="flex-end">
                <FormGroup label={t('profiles.form.name')} htmlFor={`${idPrefix}-new-profile-name`} isSoloField>
                  <Input id={`${idPrefix}-new-profile-name`} value={newName} maxLength={NAME_MAX} onChange={(event) => setNewName(event.target.value)}
                    disabled={saving} />
                </FormGroup>
                <FillButton type="button" size="small" onClick={() => void saveAsNew()} disabled={saving || newName.trim() === ''}>{t('profiles.create')}</FillButton>
                <StrokeButton type="button" size="small" onClick={() => setNaming(false)} disabled={saving}>{t('common.cancel')}</StrokeButton>
              </FlexBox>
            )}
            {notice && <Text fontSize={14} color="text-secondary">{notice}</Text>}
            {saveError && <Alert type="error" placement="inline">{errorText(saveError.code, saveError.params)}</Alert>}
          </FlexBox>
        )}
        <FormGroup label={t('upload.advanced.context')} htmlFor={`${idPrefix}-context`} isSoloField
          description={t('profiles.form.counter', { n: value.context.length, max: CONTEXT_MAX })}>
          <TextArea id={`${idPrefix}-context`} rows={3} value={value.context} maxLength={CONTEXT_MAX} placeholder={t('upload.advanced.contextHint')}
            onChange={(event) => onChange({ ...value, context: event.target.value })} disabled={saving} />
        </FormGroup>
      </FlexBox>
    </Box>
  );
}
