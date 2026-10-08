import type { Me } from '../api/auth';

type Named = Pick<Me, 'email' | 'display_name'>;

/** Tên ngắn để chào và hiện trong menu: tên hiển thị, không có thì phần trước @ của email. */
export const shortName = (user: Named): string => user.display_name?.trim() || user.email.split('@')[0];

/** Chữ cái đầu (viết hoa) cho avatar. Array.from để không cắt đôi ký tự ngoài BMP. */
export const initialOf = (user: Named): string => (Array.from(shortName(user))[0] ?? '?').toLocaleUpperCase('vi');
