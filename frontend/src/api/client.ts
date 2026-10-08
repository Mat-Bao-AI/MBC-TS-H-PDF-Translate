export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly params: Record<string, string | number>;

  constructor(status: number, code: string, params: Record<string, string | number> = {}) {
    super(code);
    this.status = status;
    this.code = code;
    this.params = params;
  }
}

export const AUTH_EXPIRED_EVENT = 'auth:expired';
/** Server báo trạng thái instance khác bản client đang giữ (quản trị viên duy nhất vừa xoá tài khoản, đăng ký vừa đóng,
 *  SMTP vừa gỡ…): AuthContext nạp lại /api/setup/status để guard và trang đổi theo, không cần tải lại trang. */
export const INSTANCE_STALE_EVENT = 'instance:stale';
const INSTANCE_CODES = new Set(['setup_required', 'setup_done', 'registration_closed', 'mail_not_configured']);

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, 'unknown');
}

export const jsonBody = (data: unknown) => JSON.stringify(data);

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('X-Requested-With', 'fetch');
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'network');
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (response.ok) return body as T;
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && typeof (detail as { code?: unknown }).code === 'string') {
    const { code, ...params } = detail as { code: string } & Record<string, string | number>;
    if (response.status === 401 && code === 'unauthenticated') {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    if (INSTANCE_CODES.has(code)) window.dispatchEvent(new Event(INSTANCE_STALE_EVENT));
    throw new ApiError(response.status, code, params);
  }
  throw new ApiError(response.status, response.status === 422 ? 'validation' : 'unknown');
}
