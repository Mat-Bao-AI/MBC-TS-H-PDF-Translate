import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Anchor, Box, Card, Dialog, FillButton, FlexBox, FormGroup, Input, Radio, RadioGroup, Select,
  StrokeButton, Text,
} from '@codecademy/gamut';
import { toApiError, type ApiError } from '../../api/client';
import { settingsApi, type CredentialInfo, type EngineMode, type Provider, type SettingsInfo } from '../../api/settings';
import {
  chosenEngine, engineLabel, initialChoice, isAvailable, modelOptions, shortModelLabel, switchMode, type EngineChoice,
} from '../../files/engines';
import { fontOptions } from '../../files/fonts';
import { errorText, t, type MessageKey } from '../../i18n/t';
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
  onChanged: (settings: SettingsInfo) => void;
};

function KeyCard({ provider, label, description, link, credential, defaultEngine, onChanged }: KeyCardProps) {
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
      </Dialog>
    </Card>
  );
}

const CACHE_KEY = 'settings:translation';
// Đo trên Chromium 1366px: thẻ chế độ ~617, thẻ Gemini ~349, thẻ Cloud ~316, tiêu đề "API key" ~29.
const SKELETON_MODE_HEIGHT = 617;
const SKELETON_GEMINI_HEIGHT = 349;
const SKELETON_CLOUD_HEIGHT = 316;

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
  // Hai ô Select là uncontrolled: tăng sau mỗi phản hồi settings để remount chúng với đúng giá trị state
  // (thứ sẽ được gửi khi bấm "Lưu") — ô chọn và state không bao giờ lệch nhau.
  const [version, setVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  // Lưu/xoá key: phần "Chế độ dịch mặc định" phản ánh server (key quyết định engine nào dùng được, server có
  // thể đổi mặc định), không giữ lựa chọn dở dang. Font đang chọn dở thì GIỮ: key không đụng tới default_font.
  const applyKeyChange = useCallback((next: SettingsInfo) => {
    cacheSet(CACHE_KEY, next);
    setSettings(next);
    setChoice(initialChoice(next));
    setVersion((current) => current + 1);
  }, []);

  // Tải trang / lưu mặc định: mọi thứ, kể cả font, theo đúng server.
  const apply = useCallback((next: SettingsInfo) => {
    applyKeyChange(next);
    setFont(next.default_font);
  }, [applyKeyChange]);

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
      apply(await settingsApi.savePreferences(engine, model, font));
      setSaved(true);
    } catch (caught) {
      setSaveError(toApiError(caught));
    } finally {
      setSaving(false);
    }
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
            defaultEngine={settings.default_engine} onChanged={applyKeyChange} />
        ))}
      </FlexBox>
    </Box>
  );
}
