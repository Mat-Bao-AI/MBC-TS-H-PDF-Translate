import { Box, Card } from '@codecademy/gamut';
import { t } from '../i18n/t';

/** Khung giữ chỗ cho một thẻ đang tải: cao gần bằng thẻ thật nên nội dung bật ra không đẩy phần bên dưới. */
export function SkeletonCard({ height }: { height: number }) {
  return (
    <Card p={24} minHeight={`${height}px`} role="status" aria-busy="true" aria-label={t('common.loading')}>
      <Box bg="background-disabled" borderRadius="md" height="24px" width="40%" />
      <Box bg="background-disabled" borderRadius="md" height="16px" width="80%" mt={16} />
      <Box bg="background-disabled" borderRadius="md" height="16px" width="65%" mt={8} />
    </Card>
  );
}
