import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import styled from '@emotion/styled';
import { useNavigate } from 'react-router-dom';
import { Box, FlexBox, Menu, MenuItem, Popover, Text } from '@codecademy/gamut';
import { GearIcon, LogoutIcon, PersonIcon, SettingsSliderVerticalIcon } from '@codecademy/gamut-icons';
import { css } from '@codecademy/gamut-styles';
import type { Me } from '../api/auth';
import { initialOf, shortName } from '../auth/identity';
import { t } from '../i18n/t';

type Props = { user: Me; onSignOut: () => void };

// Gamut không có Avatar: nút tròn tự dựng. styled.button (không phải Box as="button") vì Box không nhận
// type/aria-haspopup theo kiểu; `css` của gamut-styles hiểu token theme (bg/color/fontWeight).
const AvatarButton = styled.button(
  css({
    width: 36,
    height: 36,
    borderRadius: 'full', // thang borderRadii của Gamut: 'full' = 999px ('50%' lỗi kiểu)
    border: 'none',
    bg: 'primary',
    color: 'background',
    fontWeight: 'title',
    fontSize: 16,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    '&:focus-visible': { outline: '2px solid', outlineColor: 'primary', outlineOffset: '2px' },
  }),
);

// Vạch ngăn: MenuSeparator của Gamut thụt 16px hai bên, còn ở đây phải chạy hết bề ngang khung (cùng vạch dưới header).
// <li role="separator"> là con hợp lệ của <ul role="menu">.
const Separator = styled.li(css({ borderTop: 1, borderColor: 'border-tertiary', listStyle: 'none' }));

// Avatar nhỏ ở đầu menu: cùng chữ cái đầu với nút avatar, không bấm được.
const MenuAvatar = styled.span(
  css({
    width: 32,
    height: 32,
    flexShrink: 0,
    borderRadius: 'full',
    bg: 'primary',
    color: 'background',
    fontWeight: 'title',
    fontSize: 16,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
  }),
);

export function AccountMenu({ user, onSignOut }: Props) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const avatarRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLUListElement | null>(null);

  // Menu nằm trong portal nên có thể gắn sau lượt render mở: focus mục đầu ngay khi nó vừa gắn vào DOM
  // (không dùng FocusTrap của Gamut — xem skipFocusTrap bên dưới).
  const attachMenu = useCallback((node: HTMLUListElement | null) => {
    menuRef.current = node;
    node?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
  }, []);

  // Gamut Popover không có preventScroll khi trả focus, và FocusTrap của nó kéo trang về avatar mỗi khi cuộn.
  // Nên tự lo: Esc đóng + trả focus cho avatar; bấm ra ngoài đóng mà KHÔNG giành focus của thứ vừa bấm.
  useEffect(() => {
    if (!open) return;
    function onDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== 'Escape') return;
      setOpen(false);
      avatarRef.current?.focus({ preventScroll: true });
    }
    function onDocumentMouseDown(event: MouseEvent) {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || avatarRef.current?.contains(target)) return;
      setOpen(false);
    }
    document.addEventListener('keydown', onDocumentKeyDown);
    document.addEventListener('mousedown', onDocumentMouseDown);
    return () => {
      document.removeEventListener('keydown', onDocumentKeyDown);
      document.removeEventListener('mousedown', onDocumentMouseDown);
    };
  }, [open]);

  // Đóng một menu đang đóng là không làm gì: trả focus ở đây sẽ kéo trang về avatar (Chrome cuộn tới phần tử được focus).
  function close() {
    if (!open) return;
    setOpen(false);
    avatarRef.current?.focus({ preventScroll: true }); // chọn mục: focus về avatar, không cuộn
  }

  function go(to: string) {
    close();
    navigate(to);
  }

  function onKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key === 'Tab') {
      // Rời menu bằng Tab / Shift+Tab: đóng, focus tạm về avatar rồi để trình duyệt đi tiếp theo thứ tự tự nhiên.
      setOpen(false);
      avatarRef.current?.focus({ preventScroll: true });
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    if (items.length === 0) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    items[(index + step + items.length) % items.length].focus({ preventScroll: true });
  }

  return (
    <>
      <AvatarButton
        ref={avatarRef}
        type="button"
        aria-label={t('shell.accountMenu')}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {initialOf(user)}
      </AvatarButton>
      {/* Chỉ dựng khi mở: Popover của Gamut chạy theo dõi cuộn cả lúc đóng. skipFocusTrap: tự lo focus ở trên. */}
      {open && (
        <Popover isOpen targetRef={avatarRef} skipFocusTrap align="right" position="below">
          <Box ref={panelRef} minWidth="240px" maxWidth="320px">
            <FlexBox alignItems="center" gap={12} px={16} py={12} borderBottom={1} borderColor="border-tertiary"
              data-testid="account-menu-header" textAlign="left">
              <MenuAvatar aria-hidden="true">{initialOf(user)}</MenuAvatar>
              <Box minWidth={0}>
                <Text as="p" fontWeight="title" truncate="ellipsis" truncateLines={1}>{shortName(user)}</Text>
                <Text as="p" fontSize={14} color="text-secondary" truncate="ellipsis" truncateLines={1}>{user.email}</Text>
              </Box>
            </FlexBox>
            <Menu ref={attachMenu} role="menu" variant="fixed" aria-label={t('shell.accountMenu')} spacing="condensed"
              onKeyDown={onKeyDown}>
              <MenuItem icon={PersonIcon} onClick={() => go('/settings/account')}>{t('shell.account')}</MenuItem>
              <MenuItem icon={GearIcon} onClick={() => go('/settings/translation')}>{t('shell.translationSettings')}</MenuItem>
              {user.is_admin && (
                <MenuItem icon={SettingsSliderVerticalIcon} onClick={() => go('/settings/system')}>{t('shell.system')}</MenuItem>
              )}
              <Separator role="separator" />
              <MenuItem icon={LogoutIcon} onClick={() => { close(); onSignOut(); }}>{t('shell.logout')}</MenuItem>
            </Menu>
          </Box>
        </Popover>
      )}
    </>
  );
}
