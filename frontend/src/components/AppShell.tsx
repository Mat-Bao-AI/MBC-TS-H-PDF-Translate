import { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Alert, Anchor, Box, FlexBox, Text } from '@codecademy/gamut';
import { accountApi } from '../api/account';
import { useAuth } from '../auth/AuthContext';
import { useMeta } from '../files/useMeta';
import { t } from '../i18n/t';
import { AccountMenu } from './AccountMenu';
import { PageContainer } from './PageContainer';
import { RouterAnchor } from './RouterAnchor';

export function AppShell() {
  const { user, instance, logout, signedIn } = useAuth();
  const navigate = useNavigate();
  const meta = useMeta();
  // Đóng là xong ngay (lạc quan): gọi server lưu theo tài khoản, lỗi cũng không hiện lại trong phiên này.
  const [bannerClosed, setBannerClosed] = useState(false);

  function closeBanner() {
    if (!user) return;
    setBannerClosed(true);
    accountApi.dismissSmtpNotice().then(() => signedIn({ ...user, smtp_notice_dismissed: true }), () => undefined);
  }

  async function signOut() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <Box minHeight="100vh">
      <Box as="header" borderBottom={1} borderColor="border-tertiary" py={8}>
        <PageContainer>
          <FlexBox alignItems="center" justifyContent="space-between" gap={16}>
            <RouterAnchor to="/" variant="interface">
              <Text as="span" fontSize={20} fontWeight="title">{t('app.name')}</Text>
            </RouterAnchor>
            {user && <AccountMenu user={user} onSignOut={signOut} />}
          </FlexBox>
        </PageContainer>
      </Box>
      {user?.is_admin && !user.smtp_notice_dismissed && !bannerClosed && instance && !instance.mail_enabled && (
        <Box bg="background-selected" borderBottom={1} borderColor="border-tertiary" py={8} data-testid="smtp-banner">
          <PageContainer>
            <Alert type="notice" placement="inline" cta={{ text: t('shell.smtpBanner.cta'), onClick: () => navigate('/settings/system') }}
              onClose={closeBanner} closeButtonProps={{ tip: t('shell.smtpBanner.close') }}>
              {t('shell.smtpBanner')}
            </Alert>
          </PageContainer>
        </Box>
      )}
      <Box as="main">
        <Outlet />
      </Box>
      {meta?.source_url && (
        <FlexBox as="footer" justifyContent="center" alignItems="center" gap={8} px={16} py={24}
          borderTop={1} borderColor="border-tertiary" flexWrap="wrap">
          <Anchor href={meta.source_url} target="_blank" rel="noopener noreferrer" variant="inline">
            {t('shell.source')}
          </Anchor>
          <Text as="span" fontSize={14} color="text-secondary">{t('shell.license')}</Text>
        </FlexBox>
      )}
    </Box>
  );
}
