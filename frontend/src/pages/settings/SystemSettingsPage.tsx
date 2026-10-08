import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import styled from '@emotion/styled';
import { Alert, Card, Dialog, FillButton, FlexBox, FormGroup, Input, StrokeButton, Text, Toggle } from '@codecademy/gamut';
import { toApiError, type ApiError } from '../../api/client';
import { systemApi, type SiteUrlSource, type SmtpInfo, type SystemSettings } from '../../api/system';
import { useAuth } from '../../auth/AuthContext';
import { SkeletonCard } from '../../components/SkeletonCard';
import { SmtpFields, smtpBody, smtpFromInfo, type SmtpForm } from '../../components/SmtpFields';
import { errorText, t, type MessageKey } from '../../i18n/t';
import { cacheGet, cacheSet } from '../../lib/swrCache';

const SOURCE_LINE: Record<SmtpInfo['source'], MessageKey> = {
  settings: 'system.smtp.source.settings', env: 'system.smtp.source.env',
  none: 'system.smtp.source.none', dev_log: 'system.smtp.source.dev_log',
};
const SITE_URL_SOURCE_LINE: Record<SiteUrlSource, MessageKey> = {
  env: 'system.siteUrl.source.env', setup: 'system.siteUrl.source.setup',
};
// URL dài không có chỗ ngắt: xuống dòng giữa chừng thay vì tràn ngang ở 360px.
const SiteUrlText = styled(Text)({ overflowWrap: 'anywhere' });

/** Trạng thái một thẻ: đang gửi (ref chống bấm đúp), lỗi chung (Alert), ô sai (`invalid_smtp.field` / `invalid_limit`), thông báo xong. */
function useCardState() {
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [errorField, setErrorField] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(action: () => Promise<string>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setErrorField(null);
    setNotice(null);
    try {
      setNotice(await action());
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.code === 'invalid_smtp' && typeof apiError.params.field === 'string') setErrorField(apiError.params.field);
      else if (apiError.code === 'invalid_limit') setErrorField('limit');
      else setError(apiError);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return { busy, error, errorField, notice, run };
}

function SystemCard({ title, children }: { title: string; children: ReactNode }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <Card p={24}>
        <Text as="h2" id={headingId} variant="title-xs" mb={16}>{title}</Text>
        {children}
      </Card>
    </section>
  );
}

function CardAlerts({ error, notice }: { error: ApiError | null; notice: string | null }) {
  return (
    <>
      {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
      {notice && <Alert type="success" placement="inline">{notice}</Alert>}
    </>
  );
}

/** Địa chỉ trang dùng dựng link trong thư — chỉ đọc: đổi bằng env APP_BASE_URL (env > ghi lúc /setup), không có ô sửa. */
function SiteUrlNote({ url, source }: { url: string | null; source: SiteUrlSource | null }) {
  if (url === null || source === null) return <Alert type="notice" placement="inline">{t('system.siteUrl.unknown')}</Alert>;
  return (
    <FlexBox flexDirection="column" gap={4}>
      <SiteUrlText fontSize={14}>{t('system.siteUrl.known', { url })}</SiteUrlText>
      <Text fontSize={14} color="text-secondary">{t(SITE_URL_SOURCE_LINE[source])}</Text>
    </FlexBox>
  );
}

type SmtpCardProps = {
  info: SmtpInfo; siteUrl: string | null; siteUrlSource: SiteUrlSource | null;
  onChanged: (next: SystemSettings) => void; onReload: () => void;
};

function SmtpCard({ info, siteUrl, siteUrlSource, onChanged, onReload }: SmtpCardProps) {
  const { refreshInstance } = useAuth();
  const [form, setForm] = useState<SmtpForm>(() => smtpFromInfo(info));
  const [resetKey, setResetKey] = useState(0);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const state = useCardState();

  // Server chỉ giữ mật khẩu đã lưu khi host VÀ security không đổi so với nguồn đang có hiệu lực.
  const passwordRequired = form.host.trim().toLowerCase() !== info.host.trim().toLowerCase() || form.security !== info.security;

  const resetForm = useCallback((from: SmtpInfo) => { setForm(smtpFromInfo(from)); setResetKey((key) => key + 1); }, []);
  const mounted = useRef(false);
  // Chỉ theo các giá trị nguyên thuỷ của đúng thẻ này: lưu thẻ kia (setSettings tạo đối tượng mới) không được xoá form đang gõ dở.
  const { source, host, port, security, username, from, password_status } = info;
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; } // lần đầu form đã khởi tạo từ `info`: đừng dựng lại Select
    resetForm({ source, host, port, security, username, from, password_status });
  }, [resetForm, source, host, port, security, username, from, password_status]);

  const save = () => state.run(async () => {
    const next = await systemApi.save({ smtp: smtpBody(form) });
    onChanged(next);
    resetForm(next.smtp); // xoá mật khẩu vừa gõ khỏi form, kể cả khi các giá trị khác không đổi
    await refreshInstance(); // mail_enabled đổi → banner admin, trang đăng ký đổi theo
    return t('system.smtp.saved');
  });
  const test = () => state.run(async () => t('system.smtp.testOk', { email: (await systemApi.testMail(smtpBody(form))).sent_to }));
  const clear = () => {
    setConfirmingClear(false);
    void state.run(async () => {
      await systemApi.clearSmtp();
      // DELETE trả 204: tải lại để biết nguồn mới (env / none); get lỗi → nạp lại cả trang (đã xoá xong, không báo lỗi chung).
      await systemApi.get().then(onChanged, onReload);
      await refreshInstance();
      return t('system.smtp.cleared');
    });
  };

  return (
    <SystemCard title={t('system.smtp.title')}>
      <FlexBox flexDirection="column" gap={16}>
        <Text fontSize={14} color="text-secondary">{t(SOURCE_LINE[info.source])}</Text>
        <SiteUrlNote url={siteUrl} source={siteUrlSource} />
        <SmtpFields idPrefix="system-smtp" value={form} onChange={setForm} errorField={state.errorField} passwordStatus={info.password_status}
          passwordRequired={passwordRequired} resetKey={resetKey} />
        <CardAlerts error={state.error} notice={state.notice} />
        <FlexBox gap={8} flexWrap="wrap">
          <FillButton type="button" onClick={() => void save()} disabled={state.busy}>{t('system.smtp.save')}</FillButton>
          <StrokeButton type="button" onClick={() => void test()} disabled={state.busy}>{t('system.smtp.test')}</StrokeButton>
          <StrokeButton type="button" onClick={() => setConfirmingClear(true)} disabled={state.busy || info.source !== 'settings'}>
            {t('system.smtp.clear')}
          </StrokeButton>
        </FlexBox>
      </FlexBox>
      <Dialog
        isOpen={confirmingClear}
        title={t('system.smtp.clearTitle')}
        variant="danger"
        onRequestClose={() => setConfirmingClear(false)}
        confirmCta={{ children: t('system.smtp.clear'), onClick: clear }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setConfirmingClear(false) }}
      >
        {t('system.smtp.clearBody')}
      </Dialog>
    </SystemCard>
  );
}

function RegistrationCard({ settings, onChanged }: { settings: SystemSettings; onChanged: (next: SystemSettings) => void }) {
  const { refreshInstance } = useAuth();
  const [open, setOpen] = useState(settings.registration_open);
  const [limit, setLimit] = useState(settings.max_pending_per_user === null ? '' : String(settings.max_pending_per_user));
  const state = useCardState();

  const { registration_open, max_pending_per_user } = settings;
  // Mỗi ô chỉ theo giá trị của chính nó: lưu thẻ SMTP / "Đặt về mặc định" không được làm mất thay đổi chưa lưu của ô kia.
  useEffect(() => { setOpen(registration_open); }, [registration_open]);
  useEffect(() => { setLimit(max_pending_per_user === null ? '' : String(max_pending_per_user)); }, [max_pending_per_user]);

  const save = () => state.run(async () => {
    const next = await systemApi.save({ registration_open: open, max_pending_per_user: limit === '' ? null : Number(limit) });
    onChanged(next);
    setOpen(next.registration_open);
    setLimit(next.max_pending_per_user === null ? '' : String(next.max_pending_per_user));
    await refreshInstance(); // registration_open → trang đăng ký / link "Tạo tài khoản"
    return t('system.registration.saved');
  });

  // CHỈ hạn chờ: công tắc đăng ký đang sửa dở không được lưu theo (và vẫn hiện như đang sửa).
  const resetLimit = () => state.run(async () => {
    const next = await systemApi.save({ max_pending_per_user: null });
    onChanged(next);
    setLimit('');
    return t('system.registration.saved');
  });

  return (
    <SystemCard title={t('system.registration.title')}>
      <FlexBox flexDirection="column" gap={16}>
        <Toggle as="input" label={t('system.registration.open')} checked={open} onChange={() => setOpen((value) => !value)} />
        <FormGroup label={t('system.limit.label')} htmlFor="system-limit" description={t('system.limit.hint', { n: settings.max_pending_default })}
          error={state.errorField === 'limit' ? errorText('invalid_limit') : undefined} isSoloField>
          <Input id="system-limit" type="number" min={1} max={100} value={limit} placeholder={String(settings.max_pending_default)}
            error={state.errorField === 'limit'} onChange={(event) => setLimit(event.target.value)} />
        </FormGroup>
        <CardAlerts error={state.error} notice={state.notice} />
        <FlexBox gap={8} flexWrap="wrap">
          <FillButton type="button" onClick={() => void save()} disabled={state.busy}>
            {t('system.registration.save')}
          </FillButton>
          <StrokeButton type="button" onClick={() => void resetLimit()} disabled={state.busy}>
            {t('system.limit.reset')}
          </StrokeButton>
        </FlexBox>
      </FlexBox>
    </SystemCard>
  );
}

const CACHE_KEY = 'settings:system';
const SKELETON_SMTP_HEIGHT = 620; // 560 đã đo + khối địa chỉ trang (2 dòng 14px + khoảng cách ≈ 60 px, ước tính — chưa đo lại)
const SKELETON_REGISTRATION_HEIGHT = 300;

/** Cài đặt › Hệ thống (chỉ admin — AdminOnly ở route): hai thẻ, mỗi thẻ một nút Lưu. */
export function SystemSettingsPage() {
  const [settings, setSettingsState] = useState<SystemSettings | null>(() => cacheGet<SystemSettings>(CACHE_KEY) ?? null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);

  const setSettings = useCallback((next: SystemSettings) => {
    cacheSet(CACHE_KEY, next);
    setSettingsState(next);
  }, []);

  const load = useCallback(() => {
    setLoadError(null);
    systemApi.get().then(setSettings).catch((caught) => setLoadError(toApiError(caught)));
  }, [setSettings]);

  useEffect(() => { load(); }, [load]);

  if (loadError) {
    return <Alert type="error" placement="inline" cta={{ text: t('common.retry'), onClick: load }}>{errorText(loadError.code, loadError.params)}</Alert>;
  }
  if (!settings) {
    return (
      <FlexBox flexDirection="column" gap={24}>
        <SkeletonCard height={SKELETON_SMTP_HEIGHT} />
        <SkeletonCard height={SKELETON_REGISTRATION_HEIGHT} />
      </FlexBox>
    );
  }
  return (
    <FlexBox flexDirection="column" gap={24}>
      <SmtpCard info={settings.smtp} siteUrl={settings.site_url} siteUrlSource={settings.site_url_source}
        onChanged={setSettings} onReload={load} />
      <RegistrationCard settings={settings} onChanged={setSettings} />
    </FlexBox>
  );
}
