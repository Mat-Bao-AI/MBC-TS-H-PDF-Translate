import type { MouseEvent } from 'react';
import { Box, Breadcrumbs, FlexBox, IconButton, type Breadcrumb } from '@codecademy/gamut';
import { ArrowLeftIcon } from '@codecademy/gamut-icons';
import { useNavigate } from 'react-router-dom';
import { t } from '../i18n/t';
import { PageContainer } from './PageContainer';
import { followLink } from './RouterAnchor';

const FLOATING_TIP = { placement: 'floating' } as const;

type Props = {
  /** Tên tệp (mẩu thứ hai); bỏ trống khi chưa tải xong. */
  filename?: string;
  /** Có `section` (+ `fileId`) thì mẩu tên tệp thành liên kết tới trang tệp và `section` là mẩu cuối (trang Phiên bản). */
  fileId?: string;
  section?: string;
  /** Nút ← : về đâu (mặc định Tệp của tôi). */
  back?: { to: string; tip: string };
};

/** Dải breadcrumb riêng ngay dưới thanh trên cùng: nút quay lại + "Tệp của tôi › tên tệp [› mục]". Mọi mẩu có href điều hướng
 *  client-side (Ctrl/⌘/chuột giữa để trình duyệt lo — `followLink`). */
export function BreadcrumbBand({ filename, fileId, section, back }: Props) {
  const navigate = useNavigate();
  const target = back ?? { to: '/', tip: t('detail.back') };
  const go = (event: MouseEvent, to: string) => followLink(event, navigate, to);
  const crumbs: Breadcrumb<string>[] = [{ title: t('home.myFiles'), href: '/', payload: '/' }];
  if (filename && section && fileId) {
    crumbs.push({ title: filename, href: `/files/${fileId}`, payload: `/files/${fileId}` }, { title: section });
  } else if (filename) {
    crumbs.push({ title: filename });
  }
  return (
    <Box data-testid="breadcrumb-band" bg="background-selected" borderBottom={1} borderColor="border-tertiary" py={8}>
      <PageContainer>
        <FlexBox alignItems="center" gap={8}>
          <IconButton icon={ArrowLeftIcon} tip={target.tip} tipProps={FLOATING_TIP} href={target.to}
            onClick={(event: MouseEvent) => go(event, target.to)} size="small" variant="secondary" />
          <Box minWidth={0}>
            <Breadcrumbs crumbs={crumbs} onClick={(event, crumb) => go(event, crumb.payload)} />
          </Box>
        </FlexBox>
      </PageContainer>
    </Box>
  );
}
