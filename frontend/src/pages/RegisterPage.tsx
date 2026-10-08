import { useState, type FormEvent } from 'react';
import { Alert, FillButton, FlexBox, FormGroup, Input, Text } from '@codecademy/gamut';
import { useAuth } from '../auth/AuthContext';
import { authApi } from '../api/auth';
import { toApiError, type ApiError } from '../api/client';
import { FIELD_OF, validateCredentials, type FieldErrors } from '../auth/validate';
import { AuthCard } from '../components/AuthCard';
import { RouterAnchor, useLinkClick } from '../components/RouterAnchor';
import { errorText, t } from '../i18n/t';

export function RegisterPage() {
  const { instance } = useAuth();
  const goLogin = useLinkClick('/login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const local = validateCredentials(email, password);
    setFieldErrors(local);
    setError(null);
    if (Object.keys(local).length > 0) return;
    setBusy(true);
    try {
      await authApi.register(email.trim(), password);
      setSentTo(email.trim());
    } catch (caught) {
      const apiError = toApiError(caught);
      const field = FIELD_OF[apiError.code];
      if (field) setFieldErrors({ [field]: errorText(apiError.code) });
      else setError(apiError);
    } finally {
      setBusy(false);
    }
  }

  if (instance && !instance.registration_open) {
    return (
      <AuthCard title={t('register.closedTitle')} footer={<RouterAnchor to="/login">{t('register.login')}</RouterAnchor>}>
        <Text>{t('register.closedBody')}</Text>
      </AuthCard>
    );
  }

  if (sentTo && instance && !instance.mail_enabled) {
    // Không SMTP (spec §5): tài khoản dùng ngay, không có thư nào để kiểm.
    return (
      <AuthCard title={t('register.readyTitle')}>
        <FlexBox flexDirection="column" gap={16}>
          <Text>{t('register.readyBody')}</Text>
          <FillButton href="/login" onClick={goLogin}>{t('register.readyLogin')}</FillButton>
        </FlexBox>
      </AuthCard>
    );
  }

  if (sentTo) {
    return (
      <AuthCard title={t('register.doneTitle')} footer={<RouterAnchor to="/login">{t('register.login')}</RouterAnchor>}>
        <Text>{t('register.doneBody', { email: sentTo })}</Text>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t('register.title')}
      footer={
        <>
          <Text as="span">{t('register.hasAccount')}</Text>
          <RouterAnchor to="/login">{t('register.login')}</RouterAnchor>
        </>
      }
    >
      <form onSubmit={submit} noValidate>
        <FlexBox flexDirection="column" gap={16}>
          <FormGroup label={t('field.email')} htmlFor="email" error={fieldErrors.email} isSoloField>
            <Input id="email" name="email" type="email" autoComplete="email" value={email}
              error={Boolean(fieldErrors.email)} onChange={(event) => setEmail(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('field.password')} htmlFor="password" error={fieldErrors.password}
            description={t('field.passwordHint')} isSoloField>
            <Input id="password" name="password" type="password" autoComplete="new-password" value={password}
              error={Boolean(fieldErrors.password)} onChange={(event) => setPassword(event.target.value)} />
          </FormGroup>
          {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
          <FillButton type="submit" width="100%" disabled={busy}>{t('register.submit')}</FillButton>
        </FlexBox>
      </form>
    </AuthCard>
  );
}
