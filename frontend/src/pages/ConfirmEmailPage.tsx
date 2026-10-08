import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, FlexBox, Spinner, Text } from '@codecademy/gamut';
import { authApi } from '../api/auth';
import { toApiError, type ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthCard } from '../components/AuthCard';
import { RouterAnchor } from '../components/RouterAnchor';
import { errorText, t } from '../i18n/t';

/** Link trong thư đổi email (/confirm-email?token=…): công khai, không tạo phiên. */
export function ConfirmEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('token');
  const { user, loading, signedIn } = useAuth();
  const [error, setError] = useState<ApiError | null>(null);
  const [changedTo, setChangedTo] = useState<string | null>(null);
  // Token chỉ dùng được một lần; StrictMode chạy effect hai lần nên phải chặn lần gọi thứ hai.
  const started = useRef(false);

  useEffect(() => {
    // Đợi lượt kiểm phiên ban đầu xong: đang đăng nhập đúng tài khoản này thì cập nhật luôn email trong AuthContext.
    if (!token || loading || started.current) return;
    started.current = true;
    authApi
      .confirmEmail(token)
      .then((me) => {
        setChangedTo(me.email);
        if (user?.id === me.id) signedIn(me);
      })
      .catch((caught) => setError(toApiError(caught)));
  }, [token, loading, user, signedIn]);

  if (changedTo) {
    return (
      <AuthCard title={t('confirmEmail.title')}
        footer={<RouterAnchor to="/settings/account">{t('confirmEmail.toSettings')}</RouterAnchor>}>
        <Alert type="success" placement="inline">{t('confirmEmail.done', { email: changedTo })}</Alert>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={t('confirmEmail.title')} footer={<RouterAnchor to="/login">{t('forgot.back')}</RouterAnchor>}>
      {!token ? (
        <Alert type="error" placement="inline">{t('verify.missing')}</Alert>
      ) : error ? (
        <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>
      ) : (
        <FlexBox gap={12} alignItems="center">
          <Spinner size={24} />
          <Text>{t('confirmEmail.working')}</Text>
        </FlexBox>
      )}
    </AuthCard>
  );
}
