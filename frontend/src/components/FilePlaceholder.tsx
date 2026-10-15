import { Alert, FlexBox } from '@codecademy/gamut';
import type { ApiError } from '../api/client';
import { errorText, t } from '../i18n/t';
import { PageContainer } from './PageContainer';
import { RouterAnchor } from './RouterAnchor';
import { SkeletonCard } from './SkeletonCard';

const SKELETON_DETAIL_HEIGHT = 900;

type Props = {
  error: ApiError | null;
  onRetry: () => void;
};

/** Thân của trang theo tệp khi CHƯA có tệp để vẽ (trang tự đặt `BreadcrumbBand` phía trên, cùng vị trí với bản đầy đủ để dải không bị dựng lại): không tìm thấy (kèm đường về trang chính), lỗi tải (kèm "Thử lại") hoặc khung chờ.
 *  Trang chi tiết và trang Phiên bản dùng chung. */
export function FilePlaceholder({ error, onRetry }: Props) {
  return (
    <PageContainer py={32}>
      {error?.code === 'not_found' ? (
        <FlexBox flexDirection="column" gap={16}>
          <Alert type="error" placement="inline">{t('detail.notFound')}</Alert>
          <RouterAnchor to="/">{t('common.backHome')}</RouterAnchor>
        </FlexBox>
      ) : error ? (
        <Alert type="error" placement="inline" cta={{ text: t('common.retry'), onClick: onRetry }}>
          {errorText(error.code, error.params)}
        </Alert>
      ) : (
        <SkeletonCard height={SKELETON_DETAIL_HEIGHT} />
      )}
    </PageContainer>
  );
}
