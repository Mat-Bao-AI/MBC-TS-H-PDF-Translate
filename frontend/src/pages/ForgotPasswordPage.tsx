import { useState, type FormEvent } from 'react';
import { Alert, FillButton, FlexBox, FormGroup, Input, Text } from '@codecademy/gamut';
import { useAuth } from '../auth/AuthContext';
import { authApi } from '../api/auth';
import { toApiError, type ApiError } from '../api/client';
import { emailError } from '../auth/validate';
import { AuthCard } from '../components/AuthCard';
import { RouterAnchor } from '../components/RouterAnchor';
import { errorText, t } from '../i18n/t';

export function ForgotPasswordPage() {
  const { instance } = useAuth();
  const [email, setEmail] = useState('');
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = emailError(email);
    setFieldError(problem);
    setError(null);
    if (problem) return;
    setBusy(true);
    try {
      await authApi.forgotPassword(email.trim());
      setDone(true);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title={t('forgot.title')} footer={<RouterAnchor to="/login">{t('forgot.back')}</RouterAnchor>}>
      {instance && !instance.mail_enabled ? (
        <Alert type="notice" placement="inline">{t('mail.notConfigured')}</Alert>
      ) : done ? (
        <Alert type="success" placement="inline">{t('forgot.done')}</Alert>
      ) : (
        <form onSubmit={submit} noValidate>
          <FlexBox flexDirection="column" gap={16}>
            <Text>{t('forgot.intro')}</Text>
            <FormGroup label={t('field.email')} htmlFor="email" error={fieldError} isSoloField>
              <Input id="email" name="email" type="email" autoComplete="email" value={email}
                error={Boolean(fieldError)} onChange={(event) => setEmail(event.target.value)} />
            </FormGroup>
            {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
            <FillButton type="submit" width="100%" disabled={busy}>{t('forgot.submit')}</FillButton>
          </FlexBox>
        </form>
      )}
    </AuthCard>
  );
}
