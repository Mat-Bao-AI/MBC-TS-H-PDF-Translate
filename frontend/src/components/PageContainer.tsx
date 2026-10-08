import type { ComponentProps, ReactNode } from 'react';
import { Box } from '@codecademy/gamut';

type Props = { children: ReactNode; py?: ComponentProps<typeof Box>['py'] };

/** Khung 1200px chung: trang chủ (dải chào lẫn bảng), chi tiết, Cài đặt và phần trong của thanh trên cùng. */
export function PageContainer({ children, py = 0 }: Props) {
  return <Box maxWidth="1200px" mx="auto" px={16} py={py}>{children}</Box>;
}
