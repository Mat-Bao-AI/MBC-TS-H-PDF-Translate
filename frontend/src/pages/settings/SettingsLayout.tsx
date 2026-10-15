import type { MouseEvent } from 'react';
import styled from '@emotion/styled';
import { Box, FlexBox, Text } from '@codecademy/gamut';
import { css } from '@codecademy/gamut-styles';
import { Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { PageContainer } from '../../components/PageContainer';
import { useLinkClick } from '../../components/RouterAnchor';
import { t, type MessageKey } from '../../i18n/t';

const TABS: { to: string; label: MessageKey; admin?: boolean; advance?: boolean }[] = [
  { to: '/settings/account', label: 'settings.tab.account' },
  { to: '/settings/translation', label: 'settings.tab.translation' },
  { to: '/settings/profiles', label: 'settings.tab.profiles', advance: true },
  { to: '/settings/system', label: 'settings.tab.system', admin: true },
];

// Gamut không có SideNav: tab tự dựng bằng link thật (Ctrl/⌘+click mở tab mới vẫn được). Từ `sm` (768px): cột dọc,
// tab đang mở có viền trái; dưới đó: hàng ngang, viền dưới. Viền + chữ đậm + màu primary đi theo aria-current.
const TabLink = styled.a(
  css({
    display: 'block',
    px: 16,
    py: 12,
    color: 'text',
    textDecoration: 'none',
    whiteSpace: 'nowrap',
    borderStyle: 'solid',
    borderColor: 'transparent',
    borderWidth: { _: '0 0 2px 0', sm: '0 0 0 2px' },
    '&:hover': { color: 'primary' },
    '&:focus-visible': { outline: '2px solid', outlineColor: 'primary', outlineOffset: '-2px' },
    '&[aria-current="page"]': { borderColor: 'primary', color: 'primary', fontWeight: 'title' },
  }),
);

function Tab({ to, label, current }: { to: string; label: string; current: boolean }) {
  const onClick = useLinkClick(to);
  return (
    <TabLink href={to} aria-current={current ? 'page' : undefined} onClick={(event: MouseEvent) => onClick(event)}>
      {label}
    </TabLink>
  );
}

/** Khung chung của /settings/*: tiêu đề, cột tab (dọc từ 768px, ngang dưới đó) và nội dung tab đang mở. */
export function SettingsLayout() {
  const { pathname } = useLocation();
  const { user } = useAuth();
  return (
    <PageContainer py={32}>
      <Text as="h1" variant="title-lg">{t('settings.title')}</Text>
      <FlexBox flexDirection={{ _: 'column', sm: 'row' }} gap={24} mt={24}>
        <Box as="nav" aria-label={t('settings.tabs')} width={{ _: '100%', sm: '220px' }} flexShrink={0}>
          <FlexBox flexDirection={{ _: 'row', sm: 'column' }}>
            {TABS.filter((tab) => (!tab.admin || user?.is_admin) && (!tab.advance || user?.advance_mode)).map((tab) => (
              <Tab key={tab.to} to={tab.to} label={t(tab.label)} current={pathname === tab.to} />
            ))}
          </FlexBox>
        </Box>
        <Box flexGrow={1} minWidth={0}>
          <Outlet />
        </Box>
      </FlexBox>
    </PageContainer>
  );
}
