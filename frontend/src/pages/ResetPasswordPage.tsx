import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, FillButton, FlexBox, FormGroup, Input, Text } from '@codecademy/gamut';
import { authApi } from '../api/auth';
import { toApiError, type ApiError } from '../api/client';
import { FIELD_OF, passwordError } from '../auth/validate';
import { AuthCard } from '../components/AuthCard';
import { RouterAnchor } from '../components/RouterAnchor';
import { errorText, t } from '../i18n/t';

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = passwordError(password);
    setFieldError(problem);
    setError(null);
    if (problem) return;
    setBusy(true);
    try {
      await authApi.resetPassword(token, password);
      setDone(true);
    } catch (caught) {
      const apiError = toApiError(caught);
      if (FIELD_OF[apiError.code] === 'password') setFieldError(errorText(apiError.code));
      else setError(apiError);
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthCard title={t('reset.title')} footer={<RouterAnchor to="/forgot-password">{t('reset.requestNew')}</RouterAnchor>}>
        <Alert type="error" placement="inline">{errorText('invalid_token')}</Alert>
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard title={t('reset.title')} footer={<RouterAnchor to="/login">{t('reset.login')}</RouterAnchor>}>
        <Alert type="success" placement="inline">{t('reset.done')}</Alert>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={t('reset.title')}>
      <form onSubmit={submit} noValidate>
        <FlexBox flexDirection="column" gap={16}>
          <FormGroup label={t('field.newPassword')} htmlFor="password" error={fieldError} description={t('field.passwordHint')} isSoloField>
            <Input id="password" name="password" type="password" autoComplete="new-password" value={password}
              error={Boolean(fieldError)} onChange={(event) => setPassword(event.target.value)} />
          </FormGroup>
          {error && (
            <Alert type="error" placement="inline">
              {/* span riêng: getByText cần một phần tử chỉ chứa đúng câu lỗi */}
              <Text as="span">{errorText(error.code, error.params)}</Text>{' '}
              {error.code === 'invalid_token' && <RouterAnchor to="/forgot-password">{t('reset.requestNew')}</RouterAnchor>}
            </Alert>
          )}
          <FillButton type="submit" width="100%" disabled={busy}>{t('reset.submit')}</FillButton>
        </FlexBox>
      </form>
    </AuthCard>
  );
}
