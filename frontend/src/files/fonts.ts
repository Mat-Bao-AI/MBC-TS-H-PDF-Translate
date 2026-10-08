import type { FileItem, Meta, RetranslateChoice } from '../api/files';
import { t, type MessageKey } from '../i18n/t';
import { engineCaption, engineLabel, shortModelLabel } from './engines';

/** Ba hồ sơ font của bản dịch — cùng danh sách với backend (app.engine.fonts.PROFILE_IDS). */
export const FONT_PROFILES = ['auto', 'sans', 'serif'] as const;
export type FontProfile = (typeof FONT_PROFILES)[number];

const LABELS: Record<FontProfile, MessageKey> = { auto: 'font.auto', sans: 'font.sans', serif: 'font.serif' };
const USED: Partial<Record<string, MessageKey>> = { sans: 'font.used.sans', serif: 'font.used.serif' };

export const fontLabel = (id: string): string => (id in LABELS ? t(LABELS[id as FontProfile]) : id);

/** Options cho `Select` của Gamut (id → nhãn), theo thứ tự hiển thị. */
export const fontOptions = (): Record<string, string> =>
  Object.fromEntries(FONT_PROFILES.map((id) => [id, fontLabel(id)]));

/** "Font không chân" / "Font có chân"; null khi chưa biết font thực dùng (tệp cũ, worker giả). */
export function fontUsedCaption(fontUsed: string | null): string | null {
  const key = fontUsed ? USED[fontUsed] : undefined;
  return key ? t(key) : null;
}

/** Hồ sơ chọn sẵn trong hộp thoại "Dựng lại với font khác": sans → serif; serif hoặc chưa biết → sans. */
export const otherProfile = (fontUsed: string | null): FontProfile => (fontUsed === 'sans' ? 'serif' : 'sans');

/** Dòng mô tả của một tệp: "Dịch sang <ngôn ngữ> · <model/engine> · <Font …>" — phần nào không có thì bỏ. */
export function fileCaption(
  item: Pick<FileItem, 'engine' | 'model' | 'font_used'>, languageName: string, meta: Meta | null,
): string {
  return [t('file.translatedTo', { language: languageName }), engineCaption(item, meta), fontUsedCaption(item.font_used)]
    .filter(Boolean)
    .join(' · ');
}

/** "Tiếng Anh · Gemini 3.8 Flash · Có chân (Liberation Serif)" — đích của lượt dịch lại đang chạy (dải ở trang chi tiết).
 * Khác `fileCaption`: Google miễn phí vẫn được gọi tên — người dùng vừa chọn, cần thấy lượt này chạy bằng gì. */
export function retranslateCaption(target: RetranslateChoice, languageName: string, meta: Meta | null): string {
  const engine = target.engine === 'gemini'
    ? shortModelLabel(target.model, meta?.gemini_models) || engineLabel(target.engine, meta?.engines)
    : engineLabel(target.engine, meta?.engines);
  return [languageName, engine, fontLabel(target.font)].join(' · ');
}
