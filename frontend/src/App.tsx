import { Navigate, Route, Routes } from 'react-router-dom';
import { AdminOnly, GuestOnly, RequireAuth, SetupGate } from './auth/RequireAuth';
import { AppShell } from './components/AppShell';
import { ConfirmEmailPage } from './pages/ConfirmEmailPage';
import { FileDetailPage } from './pages/FileDetailPage';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage';
import { HomePage } from './pages/HomePage';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { ResetPasswordPage } from './pages/ResetPasswordPage';
import { AccountSettingsPage } from './pages/settings/AccountSettingsPage';
import { SettingsLayout } from './pages/settings/SettingsLayout';
import { SystemSettingsPage } from './pages/settings/SystemSettingsPage';
import { TranslationSettingsPage } from './pages/settings/TranslationSettingsPage';
import { SetupPage } from './pages/SetupPage';
import { VerifyEmailPage } from './pages/VerifyEmailPage';

export function App() {
  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
      <Route path="/register" element={<GuestOnly><RegisterPage /></GuestOnly>} />
      <Route path="/verify-email" element={<SetupGate><VerifyEmailPage /></SetupGate>} />
      <Route path="/confirm-email" element={<SetupGate><ConfirmEmailPage /></SetupGate>} />
      <Route path="/forgot-password" element={<SetupGate><ForgotPasswordPage /></SetupGate>} />
      <Route path="/reset-password" element={<SetupGate><ResetPasswordPage /></SetupGate>} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/" element={<HomePage />} />
        <Route path="/files/:id" element={<FileDetailPage />} />
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="/settings/account" replace />} />
          <Route path="account" element={<AccountSettingsPage />} />
          <Route path="translation" element={<TranslationSettingsPage />} />
          <Route path="system" element={<AdminOnly><SystemSettingsPage /></AdminOnly>} />
          <Route path="*" element={<Navigate to="/settings/account" replace />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
