/** Chỉ cho quay về đường dẫn cùng site — chặn /login?next=//evil.com chuyển người dùng ra ngoài. */
export function safeNext(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/';
  return raw;
}
