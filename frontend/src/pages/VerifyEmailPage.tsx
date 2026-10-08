import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, FlexBox, Spinner, Text } from '@codecademy/gamut';
import { authApi } from '../api/auth';
import { toApiError, type ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthCard } from '../components/AuthCard';
import { RouterAnchor } from '../components/RouterAnchor';
import { errorText, t } from '../i18n/t';

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('token');
  const navigate = useNavigate();
  const { loading, signedIn } = useAuth();
  const [error, setError] = useState<ApiError | null>(null);
  // Link mở ở trình duyệt khác với trình duyệt đã đăng ký: email đã xác nhận nhưng phải tự đăng nhập.
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  // Token chỉ dùng được một lần; StrictMode chạy effect hai lần nên phải chặn lần gọi thứ hai.
  const started = useRef(false);

  useEffect(() => {
    // Đợi AuthProvider xong lượt kiểm tra phiên đăng nhập ban đầu (GET /api/auth/me) trước khi
    // tự đăng nhập — nếu không, lượt kiểm tra đó có thể trả lời "chưa đăng nhập" muộn hơn và
    // ghi đè mất user vừa xác nhận xong (đua state).
    if (!token || loading || started.current) return;
    started.current = true;
    authApi
      .verifyEmail(token)
      .then((result) => {
        if ('id' in result) {
          signedIn(result);
          navigate('/', { replace: true });
        } else {
          setVerifiedOnly(true);
        }
      })
      .catch((caught) => setError(toApiError(caught)));
  }, [token, loading, navigate, signedIn]);

  if (verifiedOnly) {
    return (
      <AuthCard title={t('verify.title')} footer={<RouterAnchor to="/login">{t('verify.login')}</RouterAnchor>}>
        <Alert type="success" placement="inline">{t('verify.done')}</Alert>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={t('verify.title')} footer={<RouterAnchor to="/login">{t('forgot.back')}</RouterAnchor>}>
      {!token ? (
        <Alert type="error" placement="inline">{t('verify.missing')}</Alert>
      ) : error ? (
        <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>
      ) : (
        <FlexBox gap={12} alignItems="center">
          <Spinner size={24} />
          <Text>{t('verify.working')}</Text>
        </FlexBox>
      )}
    </AuthCard>
  );
}
