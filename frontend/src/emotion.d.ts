import '@emotion/react';
import type { CoreTheme } from '@codecademy/gamut-styles';

// Không có khai báo này thì mọi prop spacing/màu của Gamut (p={16}, color="primary") đều lỗi kiểu.
declare module '@emotion/react' {
  export interface Theme extends CoreTheme {}
}
