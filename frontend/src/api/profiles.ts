import { ApiError, apiFetch, jsonBody } from './client';
import type { ProfileBody, ProfileItem } from './settings';

export type RestorePresetsResult = { updated: number; created: number };
const one = (id: string) => `/api/profiles/${encodeURIComponent(id)}`;

/** /api/profiles — hồ sơ dịch của người đang đăng nhập; mẫu `preset:*` chỉ đọc (409 preset_readonly) cho tới khi được gieo thành hồ sơ riêng. */
export const profilesApi = {
  list: () => apiFetch<ProfileItem[]>('/api/profiles'),
  create: (body: ProfileBody) => apiFetch<ProfileItem>('/api/profiles', { method: 'POST', body: jsonBody(body) }),
  update: (id: string, body: ProfileBody) => apiFetch<ProfileItem>(one(id), { method: 'PUT', body: jsonBody(body) }),
  remove: (id: string) => apiFetch<void>(one(id), { method: 'DELETE' }),
  /** Đưa 5 hồ sơ gieo từ mẫu về gốc, tạo lại mẫu đã xoá (spec 2026-10-15 §5). 409 too_many_profiles ở đây nghĩa là không đủ chỗ cho
   *  các mẫu cần thêm (người có 16–19 hồ sơ cũng gặp) → đổi thành mã riêng `presets_no_room` để mọi chỗ gọi hiện đúng câu. */
  restorePresets: () => apiFetch<RestorePresetsResult>('/api/profiles/restore-presets', { method: 'POST' }).catch((caught: unknown) => {
    if (caught instanceof ApiError && caught.code === 'too_many_profiles') throw new ApiError(caught.status, 'presets_no_room', caught.params);
    throw caught;
  }),
};
