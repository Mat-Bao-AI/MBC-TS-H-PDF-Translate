import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, FillButton, FlexBox, FormGroup, Input, Text, TextButton } from '@codecademy/gamut';
import { authApi } from '../api/auth';
import { toApiError, type ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { safeNext } from '../auth/safeNext';
import { AuthCard } from '../components/AuthCard';
import { RouterAnchor } from '../components/RouterAnchor';
import { errorText, t } from '../i18n/t';

export function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { signedIn, instance } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [resent, setResent] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendError, setResendError] = useState<ApiError | null>(null);
  const deleted = params.get('deleted') === '1'; // vừa xoá tài khoản ở Cài đặt › Tài khoản

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResent(false);
    setResendError(null);
    try {
      const me = await authApi.login(email, password);
      signedIn(me);
      navigate(safeNext(params.get('next')), { replace: true });
    } catch (caught) {
      setError(toApiError(caught));
      setBusy(false);
    }
  }

  async function resend() {
    setResending(true);
    setResendError(null);
    try {
      await authApi.resendVerification(email);
      setResent(true);
    } catch (caught) {
      setResendError(toApiError(caught));
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthCard
      title={t('login.title')}
      footer={
        instance?.registration_open === false ? undefined : (
          <>
            <Text as="span">{t('login.noAccount')}</Text>
            <RouterAnchor to="/register">{t('login.register')}</RouterAnchor>
          </>
        )
      }
    >
      <form onSubmit={submit} noValidate>
        <FlexBox flexDirection="column" gap={16}>
          {deleted && <Alert type="success" placement="inline">{t('login.deleted')}</Alert>}
          {/* isSoloField: bỏ hậu tố "(optional)"/"*" mà Gamut tự thêm vào label — các field trong form này luôn bắt buộc. */}
          <FormGroup label={t('field.email')} htmlFor="email" isSoloField>
            <Input id="email" name="email" type="email" autoComplete="email" value={email}
              onChange={(event) => setEmail(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('field.password')} htmlFor="password" isSoloField>
            <Input id="password" name="password" type="password" autoComplete="current-password" value={password}
              onChange={(event) => setPassword(event.target.value)} />
          </FormGroup>
          {error && (
            <Alert type="error" placement="inline">
              <Text as="span">{errorText(error.code, error.params)}</Text>
              {error.code === 'email_unverified' && instance?.mail_enabled === false && (
                <> <Text as="span">{t('mail.notConfigured')}</Text></>
              )}
              {error.code === 'email_unverified' && instance?.mail_enabled !== false && !resent && (
                <>
                  {' '}
                  <TextButton type="button" onClick={resend} disabled={resending}>{t('login.resend')}</TextButton>
                </>
              )}
            </Alert>
          )}
          {resent && <Alert type="success" placement="inline">{t('login.resent')}</Alert>}
          {resendError && (
            <Alert type="error" placement="inline">
              <Text as="span">{errorText(resendError.code, resendError.params)}</Text>
            </Alert>
          )}
          <FillButton type="submit" width="100%" disabled={busy}>{t('login.submit')}</FillButton>
          <RouterAnchor to="/forgot-password">{t('login.forgot')}</RouterAnchor>
        </FlexBox>
      </form>
    </AuthCard>
  );
}
