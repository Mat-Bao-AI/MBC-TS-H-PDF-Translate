import type { MouseEvent, ReactNode } from 'react';
import { Anchor } from '@codecademy/gamut';
import { useNavigate } from 'react-router-dom';

type Props = { to: string; children: ReactNode; variant?: 'inline' | 'standard' | 'interface' };

/** Điều hướng client-side cho một phần tử có href thật: click thường → navigate, Ctrl/⌘/chuột giữa → để trình duyệt lo. */
export function useLinkClick(to: string) {
  const navigate = useNavigate();
  return (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    navigate(to);
  };
}

/** Anchor của Gamut không nhận `as={Link}` (lỗi kiểu) — nên tự điều hướng, vẫn giữ href thật cho Ctrl+click. */
export function RouterAnchor({ to, children, variant = 'inline' }: Props) {
  const onClick = useLinkClick(to);
  return (
    <Anchor href={to} variant={variant} onClick={onClick}>
      {children}
    </Anchor>
  );
}
