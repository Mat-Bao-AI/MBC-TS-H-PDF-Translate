import type { ReactNode } from 'react';
import { Navigate, useLocation, useSearchParams } from 'react-router-dom';
import { FlexBox, Spinner } from '@codecademy/gamut';
import { useAuth } from './AuthContext';
import { safeNext } from './safeNext';

export function FullPageSpinner() {
  return (
    <FlexBox minHeight="100vh" justifyContent="center" alignItems="center">
      <Spinner size={32} />
    </FlexBox>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, instance, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullPageSpinner />;
  if (instance?.needs_setup) return <Navigate to="/setup" replace />;
  if (!user) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  return <>{children}</>;
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, instance, loading } = useAuth();
  const [params] = useSearchParams();
  if (loading) return <FullPageSpinner />;
  if (instance?.needs_setup) return <Navigate to="/setup" replace />;
  // Đọc lại `next` từ URL hiện tại thay vì luôn về "/": LoginPage tự signIn() rồi tự navigate tới
  // safeNext(next) trong cùng một lượt cập nhật, nhưng GuestOnly có thể render lại với user mới
  // trước khi location kịp đổi (đua state), lúc đó bản thân nó cũng điều hướng — nếu hardcode "/",
  // nó ghi đè mất đích đến mà LoginPage đã định điều hướng tới.
  if (user) return <Navigate to={safeNext(params.get('next'))} replace />;
  return <>{children}</>;
}

/** Trong RequireAuth: người thường gõ thẳng URL của trang admin → về tab Tài khoản (spec 2026-10-05 §4). */
export function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!user?.is_admin) return <Navigate to="/settings/account" replace />;
  return <>{children}</>;
}

/** Route công khai (verify-email, confirm-email, forgot/reset-password): chưa cài đặt thì cũng về /setup. */
export function SetupGate({ children }: { children: ReactNode }) {
  const { instance, loading } = useAuth();
  if (loading) return <FullPageSpinner />;
  if (instance?.needs_setup) return <Navigate to="/setup" replace />;
  return <>{children}</>;
}
