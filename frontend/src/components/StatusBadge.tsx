import { Text } from '@codecademy/gamut';
import type { FileItem } from '../api/files';
import { t, type MessageKey } from '../i18n/t';

const COLORS = {
  queued: 'text-secondary',
  running: 'primary',
  done: 'feedback-success',
  error: 'feedback-error',
} as const;

// Job dịch qua API chạy 3 bước, mỗi bước tiến độ đếm lại từ 0 — hiện "Bước n/3 · x%" thay vì một con số % tụt về 0.
const STEPS: Record<string, number> = { split: 1, translate: 2, render: 3 };

const pct = (item: FileItem) => (item.total_pages > 0 ? Math.round((item.done_pages * 100) / item.total_pages) : 0);

export function statusLabel(item: FileItem): string {
  if (item.status === 'running' && STEPS[item.stage]) {
    return t('status.runningStep', { step: STEPS[item.stage], pct: pct(item) });
  }
  if (item.status === 'running' && item.total_pages > 0) {
    return t('status.runningPct', { pct: pct(item) });
  }
  return t(`status.${item.status}` as MessageKey);
}

export function StatusBadge({ item }: { item: FileItem }) {
  return (
    <Text as="span" fontSize={14} fontWeight="title" color={COLORS[item.status]}>
      {statusLabel(item)}
    </Text>
  );
}
