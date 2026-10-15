import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { authApi, type Me } from '../api/auth';
import { AUTH_EXPIRED_EVENT, INSTANCE_STALE_EVENT } from '../api/client';
import { cacheClear } from '../lib/swrCache';
import { setupApi, type InstanceStatus } from '../api/setup';

/** Trạng thái instance không nạp được (mạng, 500): coi như bình thường — một request phụ không được chặn cả app. */
export const INSTANCE_FALLBACK: InstanceStatus = { needs_setup: false, setup_token_required: false, registration_open: true, mail_enabled: true };

type AuthValue = {
  user: Me | null;
  instance: InstanceStatus | null;
  loading: boolean;
  signedIn: (user: Me) => void;
  /** Phiên đã bị server huỷ (vd vừa xoá tài khoản): chỉ quên user, không gọi /logout. */
  signedOut: () => void;
  logout: () => Promise<void>;
  /** Nạp lại /api/setup/status: sau /setup, sau khi admin lưu/xoá cấu hình, sau khi xoá tài khoản; tự chạy khi apiFetch
   *  phát INSTANCE_STALE_EVENT. */
  refreshInstance: () => Promise<void>;
  /** Nạp lại /api/auth/me — sau khi lưu công tắc Chế độ nâng cao (tab Hồ sơ dịch hiện/ẩn theo me.advance_mode). Lỗi → giữ user cũ. */
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [instance, setInstance] = useState<InstanceStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    // Một lượt cho cả hai: guard chỉ quyết định khi đã biết cả `me` lẫn `needs_setup`.
    Promise.all([authApi.me().catch(() => null), setupApi.status().catch(() => INSTANCE_FALLBACK)]).then(([me, status]) => {
      if (!alive) return;
      setUser(me);
      setInstance(status);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const expire = () => { cacheClear(); setUser(null); };
    window.addEventListener(AUTH_EXPIRED_EVENT, expire);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout().catch(() => undefined);
    cacheClear();
    setUser(null);
  }, []);
  const signedOut = useCallback(() => { cacheClear(); setUser(null); }, []);
  // Đổi người dùng: bộ nhớ đệm trang của người trước không được hiện cho người sau.
  const signedIn = useCallback((next: Me) => { cacheClear(); setUser(next); }, []);
  const refreshInstance = useCallback(async () => {
    setInstance(await setupApi.status().catch(() => INSTANCE_FALLBACK));
  }, []);

  const refreshUser = useCallback(async () => {
    const me = await authApi.me().catch(() => null);
    if (me) setUser(me);
  }, []);

  // Một chỗ cho mọi trang: setup_required / setup_done / registration_closed / mail_not_configured (apiFetch phát sự kiện).
  useEffect(() => {
    const refresh = () => { void refreshInstance(); };
    window.addEventListener(INSTANCE_STALE_EVENT, refresh);
    return () => window.removeEventListener(INSTANCE_STALE_EVENT, refresh);
  }, [refreshInstance]);

  const value = useMemo(
    () => ({ user, instance, loading, signedIn, signedOut, logout, refreshInstance, refreshUser }),
    [user, instance, loading, signedIn, signedOut, logout, refreshInstance, refreshUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth phải nằm trong AuthProvider');
  return value;
}
