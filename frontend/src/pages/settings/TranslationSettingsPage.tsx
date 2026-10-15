import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Anchor, Box, Card, Dialog, FillButton, FlexBox, FormGroup, Input, Radio, RadioGroup, Select,
  StrokeButton, Text, Toggle,
} from '@codecademy/gamut';
import { useAuth } from '../../auth/AuthContext';
import { ApiError, toApiError } from '../../api/client';
import { profilesApi } from '../../api/profiles';
import {
  TRANSLATION_SETTINGS_CACHE_KEY, settingsApi, type CredentialInfo, type EngineMode, type ProfileItem, type Provider, type SettingsInfo, type StyleValues,
} from '../../api/settings';
import {
  chosenEngine, engineLabel, initialChoice, isAvailable, modelOptions, shortModelLabel, switchMode, type EngineChoice,
} from '../../files/engines';
import { fontOptions } from '../../files/fonts';
import { STYLE_DEFAULTS, findProfile, profileOptions, styleOf } from '../../files/profiles';
import { errorText, t, type MessageKey } from '../../i18n/t';
import { ProfileFormFields } from '../../components/ProfileFormFields';
import { SkeletonCard } from '../../components/SkeletonCard';
import { formatRelative } from '../../lib/relativeTime';
import { cacheGet, cacheSet } from '../../lib/swrCache';

// Thứ tự = thứ tự hiển thị thẻ. Nhãn thẻ lấy từ backend (settings.engines) để đồng nhất với nơi khác.
const PROVIDERS: { id: Provider; description: MessageKey; link: string }[] = [
  { id: 'gemini', description: 'settings.gemini.description', link: 'https://aistudio.google.com/apikey' },
  { id: 'google_cloud', description: 'settings.cloud.description', link: 'https://console.cloud.google.com/apis/credentials' },
];

type KeyCardProps = {
  provider: Provider;
  label: string;
  description: MessageKey;
  link: string;
  credential: CredentialInfo | undefined;
  defaultEngine: string;
  /** Xoá key này sẽ tắt Chế độ nâng cao (đang bật và đây là key của engine mặc định). */
  deleteTurnsOffAdvance: boolean;
  onChanged: (settings: SettingsInfo) => void;
};

function KeyCard({ provider, label, description, link, credential, defaultEngine, deleteTurnsOffAdvance, onChanged }: KeyCardProps) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  // Lưu key Gemini đầu tiên có thể đổi mặc định sang AI (server quyết) — báo cho người dùng biết.
  const [switchedTo, setSwitchedTo] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const inputId = `key-${provider}`;

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    setSwitchedTo(null);
    try {
      const next = await settingsApi.saveKey(provider, value.trim());
      onChanged(next);
      setValue(''); // key không bao giờ hiển thị lại, kể cả key vừa gõ
      setSaved(true);
      if (defaultEngine !== 'gemini' && next.default_engine === 'gemini') {
        setSwitchedTo(shortModelLabel(next.default_model, next.gemini_models));
      }
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setConfirming(false);
    setBusy(true);
    setError(null);
    setSaved(false);
    setSwitchedTo(null);
    try {
      await settingsApi.deleteKey(provider);
      onChanged(await settingsApi.get()); // DELETE trả 204: tải lại để mặc định cập nhật theo server
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card p={24}>
      <FlexBox flexDirection="column" gap={12}>
        <Text as="h3" variant="title-xs">{label}</Text>
        <Text fontSize={14} color="text-secondary">
          {t(description)}{' '}
          <Anchor href={link} target="_blank" rel="noopener noreferrer" variant="inline">{t('settings.key.getKey')}</Anchor>
        </Text>
        <Text fontSize={14} fontWeight="title">
          {credential
            ? t('settings.key.saved', { hint: credential.hint, time: formatRelative(credential.verified_at) })
            : t('settings.key.none')}
        </Text>
        <FormGroup label={t('settings.key.label')} htmlFor={inputId} isSoloField>
          {/* new-password + data-1p-ignore / data-lpignore: trình duyệt và trình quản lý mật khẩu không
              tự điền mật khẩu đăng nhập vào đây (autoComplete="off" bị Chrome bỏ qua với ô password). */}
          <Input id={inputId} type="password" autoComplete="new-password" data-1p-ignore data-lpignore="true" value={value}
            onChange={(event) => setValue(event.target.value)} />
        </FormGroup>
        {credential && <Text fontSize={14} color="text-secondary">{t('settings.key.replaceHint')}</Text>}
        {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
        {saved && (
          <Alert type="success" placement="inline">
            {t('settings.key.ok')}
            {switchedTo && <Text as="span" display="block">{t('settings.key.switchedToAi', { model: switchedTo })}</Text>}
          </Alert>
        )}
        <FlexBox gap={8} flexWrap="wrap">
          <FillButton type="button" onClick={save} disabled={busy || value.trim() === ''}>
            {busy ? t('settings.key.checking') : t('settings.key.submit')}
          </FillButton>
          {credential && (
            <StrokeButton type="button" onClick={() => setConfirming(true)} disabled={busy}>
              {t('settings.key.delete')}
            </StrokeButton>
          )}
        </FlexBox>
        {provider === 'gemini' && <Text fontSize={14} color="text-secondary">{t('settings.key.privacy')}</Text>}
      </FlexBox>
      <Dialog
        isOpen={confirming}
        title={t('settings.key.deleteTitle')}
        variant="danger"
        onRequestClose={() => setConfirming(false)}
        confirmCta={{ children: t('settings.key.delete'), onClick: () => void remove() }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setConfirming(false) }}
      >
        {t('settings.key.deleteBody', { label })}
        {deleteTurnsOffAdvance && <Text as="p" fontSize={14} mt={8}>{t('settings.key.deleteTurnsOffAdvance')}</Text>}
      </Dialog>
    </Card>
  );
}

const CACHE_KEY = TRANSLATION_SETTINGS_CACHE_KEY;
// Đo trên Chromium 1366px: thẻ chế độ ~617, thẻ Gemini ~349, thẻ Cloud ~316, tiêu đề "API key" ~29.
const SKELETON_MODE_HEIGHT = 617;
const SKELETON_GEMINI_HEIGHT = 349;
const SKELETON_CLOUD_HEIGHT = 316;

/** Form hồ sơ tại chỗ (✎ Sửa / + Hồ sơ mới) dưới ô "Hồ sơ mặc định khi tải lên" (spec 2026-10-15 §9); null = đóng. */
type ProfileDraft = { id: string | null; title: string; name: string; style: StyleValues };

/** Cài đặt › Dịch thuật (nằm trong SettingsLayout: tiêu đề trang + khung 1200px do layout lo). */
export function TranslationSettingsPage() {
  // Lần xem trước còn trong bộ nhớ đệm thì hiện ngay (khỏi khung trống rồi bật thẻ ra), `load` làm mới ngầm.
  const [settings, setSettings] = useState<SettingsInfo | null>(() => cacheGet<SettingsInfo>(CACHE_KEY) ?? null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [choice, setChoice] = useState<EngineChoice | null>(() => {
    const cached = cacheGet<SettingsInfo>(CACHE_KEY);
    return cached ? initialChoice(cached) : null;
  });
  const [font, setFont] = useState(() => cacheGet<SettingsInfo>(CACHE_KEY)?.default_font ?? 'auto');
  const { refreshUser } = useAuth();
  const [advanceMode, setAdvanceMode] = useState(() => cacheGet<SettingsInfo>(CACHE_KEY)?.advance_mode ?? false);
  const [defaultProfile, setDefaultProfile] = useState<string | null>(() => cacheGet<SettingsInfo>(CACHE_KEY)?.default_profile ?? null);
  // Các ô Select là uncontrolled: tăng sau mỗi phản hồi settings / hồ sơ mới để remount chúng với đúng giá trị state
  // (thứ sẽ được gửi khi bấm "Lưu") — ô chọn và state không bao giờ lệch nhau.
  const [version, setVersion] = useState(0);
  // Form hồ sơ tại chỗ cũng có Select uncontrolled: mở lại (Sửa/Mới/sau khi gieo) thì remount bằng draftKey.
  const [draftKey, setDraftKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<ApiError | null>(null);

  // Lưu/xoá key: phần "Chế độ dịch mặc định" phản ánh server (key quyết định engine nào dùng được, server có
  // thể đổi mặc định, kể cả tắt Chế độ nâng cao), không giữ lựa chọn dở dang. Font đang chọn dở thì GIỮ: key không đụng tới default_font.
  const applyKeyChange = useCallback((next: SettingsInfo) => {
    cacheSet(CACHE_KEY, next);
    setSettings(next);
    setChoice(initialChoice(next));
    setAdvanceMode(next.advance_mode);
    setVersion((current) => current + 1);
    void refreshUser(); // tab Hồ sơ dịch biến mất ngay khi xoá key Gemini làm tắt Chế độ nâng cao
  }, [refreshUser]);

  // Tải trang / lưu mặc định: mọi thứ, kể cả font và công tắc, theo đúng server.
  const apply = useCallback((next: SettingsInfo) => {
    cacheSet(CACHE_KEY, next);
    setSettings(next);
    setChoice(initialChoice(next));
    setVersion((current) => current + 1);
    setFont(next.default_font);
    setAdvanceMode(next.advance_mode);
    setDefaultProfile(next.default_profile);
  }, []);

  const load = useCallback(() => {
    setLoadError(null);
    settingsApi.get().then(apply).catch((caught) => setLoadError(toApiError(caught)));
  }, [apply]);

  useEffect(() => {
    load();
  }, [load]);

  async function savePreferences() {
    if (!choice) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    const { engine, model } = chosenEngine(choice);
    try {
      apply(await settingsApi.savePreferences({
        default_engine: engine, default_model: model, default_font: font,
        advance_mode: choice.mode === 'ai' ? advanceMode : false, // động cơ thuần: server cũng tự tắt (spec 2026-10-15 §6)
        default_profile: defaultProfile,
      }));
      await refreshUser(); // tab Hồ sơ dịch trong SettingsLayout hiện/ẩn theo me.advance_mode
      setSaved(true);
    } catch (caught) {
      setSaveError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  /** Chỉ cập nhật danh sách hồ sơ + bộ nhớ đệm — KHÔNG `apply` để không mất công tắc/font đang gạt dở. */
  function mergeProfile(current: SettingsInfo, savedProfile: ProfileItem) {
    const exists = current.profiles.some((profile) => profile.id === savedProfile.id);
    const next = {
      ...current,
      profiles: exists ? current.profiles.map((profile) => (profile.id === savedProfile.id ? savedProfile : profile)) : [...current.profiles, savedProfile],
    };
    cacheSet(CACHE_KEY, next);
    setSettings(next);
  }

  async function saveDraft(current: SettingsInfo) {
    if (!draft || draftBusy) return;
    setDraftBusy(true);
    setDraftError(null);
    try {
      const body = { name: draft.name.trim(), ...draft.style };
      const savedProfile = draft.id ? await profilesApi.update(draft.id, body) : await profilesApi.create(body);
      mergeProfile(current, savedProfile);
      if (!draft.id) setDefaultProfile(savedProfile.id); // Hồ sơ mới: chọn luôn làm mặc định (người dùng bấm Lưu để chốt)
      setVersion((value) => value + 1); // ô chọn remount để hiện tên / lựa chọn mới
      setDraft(null);
    } catch (caught) {
      setDraftError(toApiError(caught));
    } finally {
      setDraftBusy(false);
    }
  }

  /** ✎ Sửa: hồ sơ là mẫu trong code (người chưa có dòng nào) thì gieo 5 mẫu trước rồi mở form trên đúng dòng vừa gieo. Danh sách trên
   *  màn hình có thể đã cũ (tab khác / một GET khác đã gieo, có khi đã sửa dòng gieo): đọc lại trước — server không còn mẫu trong code
   *  thì KHÔNG gọi khôi phục (nó đưa các dòng gieo về gốc, mất bản sửa), chỉ ánh xạ sang dòng đã gieo. */
  async function openEdit(target: ProfileItem) {
    if (draftBusy) return;
    setDraftError(null);
    setDraftKey((value) => value + 1);
    let row = target;
    if (target.kind === 'preset') {
      setDraft(null);
      setDraftBusy(true);
      try {
        let next = await settingsApi.get();
        if (next.profiles.some((profile) => profile.kind === 'preset')) {
          await profilesApi.restorePresets();
          next = await settingsApi.get();
        }
        cacheSet(CACHE_KEY, next); // chỉ danh sách hồ sơ + bộ nhớ đệm, không `apply`: công tắc/font/engine chưa Lưu giữ nguyên
        setSettings(next);
        const seeded = findProfile(next.profiles, target.id);
        // Đã gieo ở nơi khác rồi xoá đúng dòng của mẫu này: báo không tìm thấy (không gieo lại — sẽ đưa các dòng khác về mẫu).
        if (!seeded || seeded.kind === 'preset') throw new ApiError(404, 'profile_not_found');
        row = seeded;
        setDefaultProfile(seeded.id);
        setVersion((value) => value + 1);
      } catch (caught) {
        setDraftError(toApiError(caught));
        return;
      } finally {
        setDraftBusy(false);
      }
    }
    setDraft({ id: row.id, title: t('profiles.form.editTitle', { name: row.name }), name: row.name, style: styleOf(row) });
  }

  function openNew() {
    setDraftError(null);
    setDraftKey((value) => value + 1);
    setDraft({ id: null, title: t('profiles.form.createTitle'), name: '', style: STYLE_DEFAULTS });
  }

  if (loadError) {
    return <Alert type="error" placement="inline" cta={{ text: t('common.retry'), onClick: load }}>{t('settings.loadError')}</Alert>;
  }
  if (!settings || !choice) {
    // Giữ chỗ gần bằng chiều cao thật: thẻ "Chế độ dịch mặc định", tiêu đề, hai thẻ khoá API.
    return (
      <Box>
        <SkeletonCard height={SKELETON_MODE_HEIGHT} />
        <Box mt={32} height="29px" />
        <FlexBox flexDirection="column" gap={16} mt={16}>
          <SkeletonCard height={SKELETON_GEMINI_HEIGHT} />
          <SkeletonCard height={SKELETON_CLOUD_HEIGHT} />
        </FlexBox>
      </Box>
    );
  }

  const geminiAvailable = isAvailable(settings, 'gemini');
  const plainEngines = settings.engines.filter((engine) => engine.mode === 'plain');
  const needsKeyHint = !geminiAvailable || plainEngines.some((engine) => engine.available === false);
  const credentialOf = (provider: Provider) => settings.credentials.find((item) => item.provider === provider);
  const selected = findProfile(settings.profiles, defaultProfile);
  const customCount = settings.profiles.filter((profile) => profile.kind === 'custom').length;

  return (
    <Box>
      <Card p={24}>
        <FlexBox flexDirection="column" gap={16}>
          <Text as="h2" variant="title-xs">{t('settings.mode.title')}</Text>
          <Box>
            <Text as="p" fontSize={14} mb={4}>{t('settings.mode.legend')}</Text>
            <RadioGroup name="default-mode" htmlForPrefix="default-mode" aria-label={t('settings.mode.legend')}
              onChange={(event) => setChoice(switchMode(settings, choice, event.target.value as EngineMode))}>
              <Radio label={t('mode.plain')} value="plain" checked={choice.mode === 'plain'} />
              <Radio label={t('mode.ai')} value="ai" checked={choice.mode === 'ai'} disabled={!geminiAvailable} />
            </RadioGroup>
            {choice.mode === 'plain' && settings.advance_mode && (
              <Text fontSize={14} color="text-secondary" mt={4}>{t('settings.advance.plainTurnsOff')}</Text>
            )}
          </Box>
          {choice.mode === 'plain' ? (
            <Box>
              <Text as="p" fontSize={14} mb={4}>{t('settings.engine')}</Text>
              <RadioGroup name="default-engine" htmlForPrefix="default-engine" aria-label={t('settings.engine')}
                onChange={(event) => setChoice({ ...choice, engine: event.target.value })}>
                {plainEngines.map((engine) => (
                  <Radio key={engine.id} label={engine.label} value={engine.id} checked={choice.engine === engine.id}
                    disabled={engine.available === false} />
                ))}
              </RadioGroup>
            </Box>
          ) : (
            <FormGroup label={t('settings.model')} htmlFor="default-model" isSoloField>
              <Select key={`model-${version}`} id="default-model" defaultValue={choice.model} options={modelOptions(settings.gemini_models)}
                disabled={!geminiAvailable} onChange={(event) => setChoice({ ...choice, model: event.target.value })} />
            </FormGroup>
          )}
          {needsKeyHint && <Text fontSize={14} color="text-secondary">{t('settings.needKey')}</Text>}
          <FormGroup label={t('font.field')} htmlFor="default-font" isSoloField>
            <Select key={`font-${version}`} id="default-font" defaultValue={font}
              options={fontOptions()} onChange={(event) => setFont(event.target.value)} />
          </FormGroup>
          {choice.mode === 'ai' && (
            <>
              <Box>
                <Toggle as="input" label={t('settings.advance.toggle')} checked={advanceMode} onChange={() => setAdvanceMode((value) => !value)} />
                <Text fontSize={14} color="text-secondary" mt={4}>{t('settings.advance.hint')}</Text>
                {advanceMode !== settings.advance_mode && (
                  <Text fontSize={14} color="text-secondary" mt={4} data-testid="advance-unsaved">{t('settings.advance.unsaved')}</Text>
                )}
              </Box>
              <FormGroup label={t('settings.advance.defaultProfile')} htmlFor="default-profile" isSoloField>
                <Select key={`profile-${version}`} id="default-profile" defaultValue={defaultProfile ?? ''} options={profileOptions(settings.profiles)}
                  disabled={!advanceMode} onChange={(event) => setDefaultProfile(event.target.value || null)} />
              </FormGroup>
              {advanceMode && (
                <>
                  <FlexBox gap={8} flexWrap="wrap">
                    <StrokeButton type="button" size="small" onClick={() => selected && void openEdit(selected)} disabled={!selected || draftBusy}>
                      {t('settings.advance.editProfile')}
                    </StrokeButton>
                    <StrokeButton type="button" size="small" onClick={openNew} disabled={customCount >= settings.profile_limit || draftBusy}>
                      {t('settings.advance.newProfile')}
                    </StrokeButton>
                  </FlexBox>
                  {(draft || draftError) && (
                    <Box key={draftKey} border={1} borderStyle="solid" borderColor="border-tertiary" borderRadius="md" p={16} data-testid="profile-draft">
                      {draft && (
                        <>
                          <Text as="h3" variant="title-xs" mb={12}>{draft.title}</Text>
                          <ProfileFormFields idPrefix="settings-profile" name={draft.name} style={draft.style}
                            onNameChange={(name) => setDraft({ ...draft, name })} onStyleChange={(style) => setDraft({ ...draft, style })} />
                        </>
                      )}
                      {draftError && <Box mt={draft ? 12 : 0}><Alert type="error" placement="inline">{errorText(draftError.code, draftError.params)}</Alert></Box>}
                      <FlexBox gap={8} mt={12}>
                        {draft && (
                          <FillButton type="button" size="small" onClick={() => void saveDraft(settings)} disabled={draftBusy || draft.name.trim() === ''}>
                            {t('profiles.form.save')}
                          </FillButton>
                        )}
                        <StrokeButton type="button" size="small" onClick={() => { setDraft(null); setDraftError(null); }} disabled={draftBusy}>
                          {t('common.cancel')}
                        </StrokeButton>
                      </FlexBox>
                    </Box>
                  )}
                </>
              )}
            </>
          )}
          {saveError && <Alert type="error" placement="inline">{errorText(saveError.code, saveError.params)}</Alert>}
          {saved && <Alert type="success" placement="inline">{t('settings.saved')}</Alert>}
          <Box>
            <FillButton type="button" onClick={savePreferences} disabled={saving}>{t('settings.save')}</FillButton>
          </Box>
        </FlexBox>
      </Card>
      <Text as="h2" variant="title-sm" mt={32}>{t('settings.keys.title')}</Text>
      <FlexBox flexDirection="column" gap={16} mt={16}>
        {PROVIDERS.map((provider) => (
          <KeyCard key={provider.id} provider={provider.id} label={engineLabel(provider.id, settings.engines)}
            description={provider.description} link={provider.link} credential={credentialOf(provider.id)}
            defaultEngine={settings.default_engine} onChanged={applyKeyChange}
            deleteTurnsOffAdvance={settings.advance_mode && provider.id === 'gemini' && settings.default_engine === 'gemini'} />
        ))}
      </FlexBox>
    </Box>
  );
}
