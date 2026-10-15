import { apiFetch, jsonBody } from './client';
import type { EngineInfo, ModelInfo, StyleField, StyleValues } from './settings';

export type FileStatus = 'queued' | 'running' | 'done' | 'error';
/** Bốn lựa chọn của một lượt dịch lại: thân `POST /api/files/{id}/retranslate` và `settings` của hàng loạt. */
export type RetranslateChoice = { language: string; engine: string; model: string | null; font: string };
/** Ảnh chụp cấu hình nâng cao của một bản dịch (spec 2026-10-14 §3) — bản sao giá trị; null = cơ bản. */
export type Snapshot = {
  schema: number;
  mode: 'advanced';
  profile: { id: string; name: string; kind: 'preset' | 'custom' } | null;
  style: Partial<StyleValues> | null; // có hồ sơ: đủ 9 trường; không hồ sơ: chỉ trường đã gửi
  overrides: StyleField[];
  document_context: string | null;
};
/** Một bản cũ trong kho (GET /api/files/{id}.versions); `available` = tệp còn trên đĩa. */
export type FileVersion = {
  id: string; version_no: number; language: string; engine: string; model: string | null; font: string; font_used: string | null;
  config: Snapshot | null; untranslated: number; finished_at: string | null; archived_at: string; available: boolean;
  has_tables: boolean; // bảng đoạn đã dịch đi theo bản (spec 2026-10-15 §3) — false với bản cất trước 1b và tệp Google miễn phí
  translated_at: string | null; // lúc bản này được dịch (spec 2026-10-15 §4); null với bản cất trước 1b → UI lùi về archived_at
  restored_from: number | null; // bản này từng là bản sao của "Bản N"
};
/** Trường nâng cao của một lượt dịch (tải lên / dịch lại đơn); chỉ gửi khi dịch bằng AI và Chế độ nâng cao bật. */
export type AdvancedChoice = { profile: string | null; style: Partial<StyleValues> | null; context: string | null };
export type RetranslateRequest = RetranslateChoice & Partial<AdvancedChoice>;
export type FileItem = {
  id: string;
  filename: string;
  language: string;
  status: FileStatus;
  engine: string;
  model: string | null;
  stage: string;
  done_pages: number;
  total_pages: number;
  untranslated: number;
  message: string;
  created_at: string;
  finished_at: string | null;
  font: string; // auto | sans | serif — lựa chọn lúc tải lên / lần dựng lại xong gần nhất
  font_used: string | null; // sans | serif thực dùng; null = chưa biết (tệp cũ, worker giả)
  rebuild_font: string | null; // hồ sơ font của lượt dựng lại / dịch lại đang chờ; null = không có
  rebuilding: boolean; // dựng lại FONT (0 lời gọi API) — dịch lại từ đầu là `retranslating`, hai cờ không cùng bật
  rebuild_error: string; // lý do lần dựng lại HOẶC dịch lại gần nhất thất bại ("" = không có) — bản dịch trước vẫn giữ
  retranslating: boolean; // tệp đã xong đang dịch lại từ đầu: bản cũ vẫn xem/tải được tới khi bản mới thay vào
  retranslate_to: RetranslateChoice | null; // lựa chọn của lượt dịch lại đó (font = rebuild_font); null = không dịch lại
  version_no: number; // số của bản hiện tại ("Bản N"); +1 mỗi lần dịch lại tệp đã xong thành công
  config: Snapshot | null; // ảnh chụp cấu hình nâng cao của bản hiện tại; null = cơ bản
  translated_at: string | null; // lúc bản hiện tại hoàn tất; null khi chưa xong (UI lùi về finished_at)
  restored_from: number | null; // bản hiện tại là bản sao của "Bản N" (khôi phục, spec 2026-10-15 §2); null = dịch thật
  restoring: boolean; // đang khôi phục một bản cũ (retranslating cũng true: bản hiện tại còn xem/tải được tới khi thay)
  restore_version: string | null; // id bản nguồn của lượt khôi phục đang chờ
  versions?: FileVersion[]; // chỉ ở GET /api/files/{id}, bản mới nhất trước
};
export type FilePage = { items: FileItem[]; total: number; page: number; page_size: number };
export type Language = { code: string; name: string };
export type Meta = {
  languages: Language[];
  default_language: string;
  max_upload_mb: number;
  source_url: string;
  engines: EngineInfo[];
  gemini_models: ModelInfo[];
};
export type SortKey = 'created' | 'name' | 'status';
export type SortDir = 'asc' | 'desc';
/** Chọn nhiều tệp: đúng các id (1–100) hoặc mọi tệp khớp bộ lọc `q` ("Chọn tất cả N tệp"). */
export type BulkSelection = { ids: string[] } | { all: true; q: string };
export type BulkDeleteBody = BulkSelection;
export type BulkDeleteResult = { deleted: number; skipped_running: number };
/** `settings: null` = giữ cài đặt riêng của từng tệp. */
export type BulkRetranslateBody = BulkSelection & { settings: RetranslateChoice | null };
export type BulkRetranslateResult = { queued: number; skipped_pending: number; skipped_limit: number; limit: number };
export type DownloadKind = 'translated' | 'original';

export const PAGE_SIZE = 20;
const one = (id: string) => `/api/files/${encodeURIComponent(id)}`;

export const filesApi = {
  list: (q: string, page: number, sort: SortKey = 'created', dir: SortDir = 'desc') =>
    apiFetch<FilePage>(`/api/files?${new URLSearchParams({ q, page: String(page), page_size: String(PAGE_SIZE), sort, dir })}`),
  get: (id: string) => apiFetch<FileItem>(one(id)),
  upload: (file: File, language: string, engine?: string, model?: string | null, font?: string, advanced?: AdvancedChoice | null) => {
    const form = new FormData();
    form.append('file', file);
    form.append('language', language);
    if (engine) form.append('engine', engine);
    if (model) form.append('model', model);
    if (font) form.append('font', font); // không gửi = server dùng font mặc định trong Cài đặt
    // Server coi MỌI trường nâng cao có mặt (kể cả style={}) là "có gửi" và từ chối khi Chế độ nâng cao tắt:
    // chỉ thêm khi có nội dung thật.
    if (advanced?.profile) form.append('profile', advanced.profile);
    if (advanced?.style && Object.keys(advanced.style).length > 0) form.append('style', JSON.stringify(advanced.style));
    if (advanced?.context?.trim()) form.append('context', advanced.context);
    return apiFetch<FileItem>('/api/files', { method: 'POST', body: form });
  },
  retranslate: (id: string, body: RetranslateRequest) =>
    apiFetch<FileItem>(`${one(id)}/retranslate`, { method: 'POST', body: jsonBody(body) }),
  bulkRetranslate: (body: BulkRetranslateBody) =>
    apiFetch<BulkRetranslateResult>('/api/files/bulk-retranslate', { method: 'POST', body: jsonBody(body) }),
  rebuild: (id: string, font: string) =>
    apiFetch<FileItem>(`${one(id)}/rebuild`, { method: 'POST', body: jsonBody({ font }) }),
  restoreVersion: (id: string, versionId: string) =>
    apiFetch<FileItem>(`${one(id)}/versions/${encodeURIComponent(versionId)}/restore`, { method: 'POST' }),
  remove: (id: string) => apiFetch<void>(one(id), { method: 'DELETE' }),
  bulkDelete: (body: BulkDeleteBody) =>
    apiFetch<BulkDeleteResult>('/api/files/bulk-delete', { method: 'POST', body: jsonBody(body) }),
  meta: () => apiFetch<Meta>('/api/meta'),
  downloadUrl: (id: string, kind: DownloadKind) => `${one(id)}/download?kind=${kind}`,
  versionUrl: (id: string, versionId: string, inline: boolean) =>
    `${one(id)}/versions/${encodeURIComponent(versionId)}/download${inline ? '?inline=1' : ''}`,
  viewUrl: (id: string, kind: DownloadKind) => `${one(id)}/download?kind=${kind}&inline=1`,
};

export const isPending = (item: FileItem) => item.status === 'queued' || item.status === 'running';

/** Có bản dịch để xem / tải: đã xong, hoặc đang dựng lại font / dịch lại từ đầu (bản cũ giữ tới khi bản mới thay vào). */
export const hasTranslation = (item: FileItem) => item.status === 'done' || item.rebuilding || item.retranslating;
