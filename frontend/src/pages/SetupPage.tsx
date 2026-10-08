import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Alert, FillButton, FlexBox, FormGroup, Input, StrokeButton, Text } from '@codecademy/gamut';
import { toApiError, type ApiError } from '../api/client';
import { setupApi } from '../api/setup';
import { systemApi } from '../api/system';
import { useAuth } from '../auth/AuthContext';
import { FullPageSpinner } from '../auth/RequireAuth';
import { emailError, passwordError } from '../auth/validate';
import { AuthCard } from '../components/AuthCard';
import { SmtpFields, emptySmtp, smtpBody, type SmtpForm } from '../components/SmtpFields';
import { errorText, t } from '../i18n/t';

type Step1Field = 'name' | 'email' | 'password' | 'confirm' | 'token';
const FIELD_OF_CODE: Partial<Record<string, Step1Field>> = {
  invalid_display_name: 'name', invalid_email: 'email', invalid_password: 'password', invalid_setup_token: 'token',
};

/** Trình cài đặt lần đầu (spec 2026-10-05 §3): bước 1 tạo admin + đăng nhập; bước 2 (state trang) SMTP bỏ qua được. */
export function SetupPage() {
  const { instance, loading, signedIn, refreshInstance } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [token, setToken] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<Step1Field, string>>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [smtp, setSmtp] = useState<SmtpForm>(emptySmtp);
  const [smtpField, setSmtpField] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (loading || !instance) return <FullPageSpinner />;
  // Bước 1 chỉ khi còn cần cài đặt (tải lại trang sau bước 1 / người khác vừa cài xong → về trang chủ, RequireAuth lo tiếp).
  // Bước 2 nằm trong state: sau bước 1 needs_setup đã false nhưng trang KHÔNG tự chuyển hướng giữa chừng.
  if (step === 1 && !instance.needs_setup) return <Navigate to="/" replace />;

  async function submitStep1(event: FormEvent) {
    event.preventDefault();
    const local = {
      email: emailError(email), password: passwordError(password),
      confirm: password !== confirm ? t('setup.password.mismatch') : undefined,
    };
    const problems = Object.fromEntries(Object.entries(local).filter(([, message]) => message)) as Partial<Record<Step1Field, string>>;
    setFieldErrors(problems);
    setError(null);
    if (Object.keys(problems).length > 0) return; // không gọi API
    setBusy(true);
    try {
      const me = await setupApi.create({
        display_name: name.trim() || null, email: email.trim(), password,
        ...(instance!.setup_token_required ? { setup_token: token.trim() } : {}),
      });
      signedIn(me);
      setStep(2); // TRƯỚC refreshInstance: khi needs_setup đổi, guard của bước 1 ở trên không còn áp dụng
      void refreshInstance();
    } catch (caught) {
      const apiError = toApiError(caught);
      const field = FIELD_OF_CODE[apiError.code];
      if (field) setFieldErrors({ [field]: errorText(apiError.code) });
      else setError(apiError);
      // setup_done (người khác cài xong trước): apiFetch phát INSTANCE_STALE_EVENT → AuthContext nạp lại trạng thái → guard
      // ở trên đưa người dùng tới đăng nhập thay vì kẹt ở bước 1.
    } finally {
      setBusy(false);
    }
  }

  async function runSmtp(action: () => Promise<string | null>) {
    setBusy(true);
    setError(null);
    setSmtpField(null);
    setNotice(null);
    try {
      setNotice(await action());
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.code === 'invalid_smtp' && typeof apiError.params.field === 'string') setSmtpField(apiError.params.field);
      else setError(apiError);
    } finally {
      setBusy(false);
    }
  }
  const testMail = () => runSmtp(async () => t('system.smtp.testOk', { email: (await systemApi.testMail(smtpBody(smtp))).sent_to }));
  const finish = () => runSmtp(async () => {
    await systemApi.save({ smtp: smtpBody(smtp) });
    await refreshInstance();
    navigate('/', { replace: true });
    return null;
  });
  // Bỏ qua cũng ĐỢI trạng thái mới: lượt nạp lại sau bước 1 có thể chưa về — tới `/` khi `needs_setup` còn true thì
  // RequireAuth đẩy ngược về /setup và trang mất bước 2 (bấm nhanh như E2E là gặp).
  const skip = () => runSmtp(async () => {
    await refreshInstance();
    navigate('/', { replace: true });
    return null;
  });

  if (step === 2) {
    return (
      <AuthCard title={t('setup.title2')} step={t('setup.step2')} maxWidth="560px">
        <FlexBox flexDirection="column" gap={16}>
          <Text>{t('setup.smtp.intro')}</Text>
          <SmtpFields idPrefix="setup-smtp" value={smtp} onChange={setSmtp} errorField={smtpField} passwordStatus="none" />
          {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
          {notice && <Alert type="success" placement="inline">{notice}</Alert>}
          <FlexBox gap={8} flexWrap="wrap">
            <FillButton type="button" onClick={() => void finish()} disabled={busy}>{t('setup.finish')}</FillButton>
            <StrokeButton type="button" onClick={() => void testMail()} disabled={busy}>{t('system.smtp.test')}</StrokeButton>
            <StrokeButton type="button" onClick={() => void skip()} disabled={busy}>{t('setup.skip')}</StrokeButton>
          </FlexBox>
        </FlexBox>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={t('setup.title1')} step={t('setup.step1')}>
      <form onSubmit={submitStep1} noValidate>
        <FlexBox flexDirection="column" gap={16}>
          <Text>{t('setup.intro')}</Text>
          <FormGroup label={t('setup.displayName')} htmlFor="setup-name" error={fieldErrors.name} isSoloField>
            <Input id="setup-name" value={name} maxLength={50} autoComplete="nickname" error={Boolean(fieldErrors.name)}
              onChange={(event) => setName(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('field.email')} htmlFor="setup-email" error={fieldErrors.email} isSoloField>
            <Input id="setup-email" type="email" autoComplete="email" value={email} error={Boolean(fieldErrors.email)}
              onChange={(event) => setEmail(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('field.password')} htmlFor="setup-password" description={t('field.passwordHint')} error={fieldErrors.password} isSoloField>
            <Input id="setup-password" type="password" autoComplete="new-password" value={password} error={Boolean(fieldErrors.password)}
              onChange={(event) => setPassword(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('setup.confirmPassword')} htmlFor="setup-confirm" error={fieldErrors.confirm} isSoloField>
            <Input id="setup-confirm" type="password" autoComplete="new-password" value={confirm} error={Boolean(fieldErrors.confirm)}
              onChange={(event) => setConfirm(event.target.value)} />
          </FormGroup>
          {instance.setup_token_required && (
            <FormGroup label={t('setup.token')} htmlFor="setup-token" description={t('setup.token.hint')} error={fieldErrors.token} isSoloField>
              <Input id="setup-token" type="password" autoComplete="off" value={token} error={Boolean(fieldErrors.token)}
                onChange={(event) => setToken(event.target.value)} />
            </FormGroup>
          )}
          {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
          <FillButton type="submit" width="100%" disabled={busy}>{t('setup.submit')}</FillButton>
        </FlexBox>
      </form>
    </AuthCard>
  );
}
