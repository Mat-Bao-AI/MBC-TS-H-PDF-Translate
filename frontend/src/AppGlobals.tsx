import { css, Global, useTheme } from '@emotion/react';
import { Reboot } from '@codecademy/gamut-styles';
import { Variables } from '@codecademy/gamut-styles/dist/globals/Variables';

// Tái hiện phần không-phải-font của `Typography` trong Gamut (h1–h6, small) mà KHÔNG có @font-face:
// Typography gốc nạp Apercu/Suisse từ www.codecademy.com trên mọi lượt xem trang.
function Headings() {
  const theme = useTheme();
  const styles = css`
    h1,
    h2,
    h3,
    h4,
    h5,
    h6 {
      margin-bottom: ${theme.spacing[16]};
      font-weight: ${theme.fontWeight.title};
      line-height: ${theme.lineHeight.title};
    }
    h1 {
      font-size: ${theme.fontSize[64]};
    }
    h2 {
      font-size: ${theme.fontSize[44]};
    }
    h3 {
      font-size: ${theme.fontSize[34]};
    }
    h4 {
      font-size: ${theme.fontSize[26]};
    }
    h5 {
      font-size: ${theme.fontSize[22]};
    }
    h6 {
      font-size: ${theme.fontSize[20]};
    }
    small {
      font-size: ${theme.fontSize[14]};
      font-weight: ${theme.fontWeight.base};
    }
  `;
  return <Global styles={styles} />;
}

// Dùng cùng `<GamutProvider theme={appTheme} useGlobals={false}>`: render đúng một lần ở gốc ứng dụng.
export function AppGlobals() {
  const theme = useTheme();
  return (
    <>
      <Headings />
      <Reboot theme={theme} />
      <Variables variables={theme._variables} />
    </>
  );
}
