import type { Meta } from '../api/files';
import { errorText } from '../i18n/t';

/** Lý do tệp không tải lên được (không phải .pdf / quá giới hạn), hoặc null nếu hợp lệ. Dùng chung cho hộp tải lên và vùng kéo thả. */
export function pdfError(file: File, meta: Meta | null): string | null {
  if (!file.name.toLowerCase().endsWith('.pdf')) return errorText('not_pdf');
  if (meta && file.size > meta.max_upload_mb * 1024 * 1024) return errorText('too_large', { mb: meta.max_upload_mb });
  return null;
}
