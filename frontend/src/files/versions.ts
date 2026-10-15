import { filesApi, type DownloadKind, type FileItem, type FileVersion, type Meta, type Snapshot } from '../api/files';
import { t } from '../i18n/t';
import { formatRelative } from '../lib/relativeTime';
import { engineCaption, engineLabel } from './engines';
import { fontLabel, fontUsedCaption } from './fonts';
import { STYLE_FIELDS, fieldLabel, valueLabel, type EnumField } from './profiles';

/** Khoá bộ nhớ đệm của GET /api/files/{id} — trang chi tiết và trang Phiên bản dùng chung (khôi phục ghi item mới vào đây). */
export const fileCacheKey = (id: string) => `file:${id}`;

/** Bản hiện tại (id null) hoặc một bản cũ — cùng dáng để so cấu hình (spec 2026-10-15 §2). `time` = lúc bản được dịch
 *  (`translated_at`); bản cất trước đợt 1b không có → lùi về `archived_at` và `timeIsArchive` = true (UI chú "(lúc bị thay)"). */
export type VersionEntry = {
  id: string | null; version_no: number; language: string; engine: string; model: string | null; font: string; font_used: string | null;
  config: Snapshot | null; time: string | null; timeIsArchive: boolean; available: boolean; has_tables: boolean; restored_from: number | null;
};

export const currentEntry = (item: FileItem): VersionEntry => ({
  id: null, version_no: item.version_no, language: item.language, engine: item.engine, model: item.model, font: item.font,
  font_used: item.font_used, config: item.config, time: item.translated_at ?? item.finished_at, timeIsArchive: false, available: true,
  has_tables: true, // không dùng cho bản hiện tại (chỉ khôi phục bản cũ)
  restored_from: item.restored_from,
});

export const fromVersion = (version: FileVersion): VersionEntry => ({
  id: version.id, version_no: version.version_no, language: version.language, engine: version.engine, model: version.model,
  font: version.font, font_used: version.font_used, config: version.config, time: version.translated_at ?? version.archived_at,
  timeIsArchive: version.translated_at === null, available: version.available, has_tables: version.has_tables, restored_from: version.restored_from,
});

/** Mọi bản theo `version_no` tăng dần, bản hiện tại cuối — thanh mốc của trang Phiên bản. */
export const entriesOf = (item: FileItem): VersionEntry[] =>
  [...(item.versions ?? [])].sort((a, b) => a.version_no - b.version_no).map(fromVersion).concat(currentEntry(item));

/** Mã ngôn ngữ → tên tiếng Việt (không có trong danh sách thì giữ nguyên mã). */
export const languageNamer = (meta: Meta | null) => (code: string): string =>
  meta?.languages.find((language) => language.code === code)?.name ?? code;

export type ConfigRow = { key: string; label: string; value: string };

const engineText = (entry: VersionEntry, meta: Meta | null) => engineCaption(entry, meta) ?? engineLabel(entry.engine, meta?.engines);

/** 14 hàng cố định (cùng thứ tự cho mọi bản → so theo chỉ số): ngôn ngữ, động cơ, font, hồ sơ, 9 trường, ngữ cảnh. */
export function configRows(entry: VersionEntry, meta: Meta | null, languageName: (code: string) => string): ConfigRow[] {
  const style = entry.config?.style ?? null;
  const none = t('detail.config.none');
  const styleRows: ConfigRow[] = STYLE_FIELDS.map((field) => {
    const raw = style?.[field];
    const value = raw === undefined || raw === null ? none
      : field === 'custom_instructions' ? (raw || none) : valueLabel(field as EnumField, raw);
    return { key: field, label: fieldLabel(field), value };
  });
  return [
    { key: 'language', label: t('detail.config.language'), value: languageName(entry.language) },
    { key: 'engine', label: t('detail.config.engine'), value: engineText(entry, meta) },
    { key: 'font', label: t('detail.config.font'), value: fontUsedCaption(entry.font_used) ?? fontLabel(entry.font) },
    { key: 'profile', label: t('detail.config.profile'), value: entry.config?.profile?.name ?? t('detail.version.basic') },
    ...styleRows,
    { key: 'context', label: t('detail.config.context'), value: entry.config?.document_context ?? none },
  ];
}

/** "hôm nay lúc 09:12" / "hôm nay lúc 09:12 (lúc bị thay)" — null khi chưa có giờ. */
export const entryTime = (entry: VersionEntry): string | null =>
  entry.time ? (entry.timeIsArchive ? t('versions.archivedAt', { time: formatRelative(entry.time) }) : formatRelative(entry.time)) : null;

/** "Bản 3 · hôm nay lúc 09:12 · Gemini 3.8 Flash · Tài liệu kỹ thuật · khôi phục từ Bản 1 · hiện tại". */
export function entryHeadline(entry: VersionEntry, meta: Meta | null): string {
  return [
    t('detail.version.label', { n: entry.version_no }),
    entryTime(entry),
    engineText(entry, meta),
    entry.config?.profile?.name ?? t('detail.version.basic'),
    entry.restored_from !== null ? t('detail.restoredFrom', { k: entry.restored_from }) : null,
    entry.id === null ? t('detail.version.current') : null,
  ].filter(Boolean).join(' · ');
}

/** URL khung xem: bản cũ (`versionId`) có đường riêng; bản hiện tại thêm `&v=<finished_at>` để dựng lại xong không hiện bản cũ từ cache. */
export function frameUrl(item: FileItem, kind: DownloadKind, versionId: string | null): string {
  if (kind === 'translated' && versionId) return filesApi.versionUrl(item.id, versionId, true);
  const url = filesApi.viewUrl(item.id, kind);
  return kind === 'translated' && item.finished_at ? `${url}&v=${encodeURIComponent(item.finished_at)}` : url;
}
