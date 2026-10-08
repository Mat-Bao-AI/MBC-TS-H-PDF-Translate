import type { ReactNode } from 'react';
import { GamutProvider } from '@codecademy/gamut-styles';
import { AppGlobals } from './AppGlobals';
import { appTheme } from './theme';

// useGlobals={false}: Typography của Gamut chèn @font-face trỏ tới codecademy.com; globals tự render trong <AppGlobals />.
// main.tsx và test dùng chung component này để dây nối trên không thể lệch khỏi thứ được kiểm.
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <GamutProvider theme={appTheme} useGlobals={false}>
      <AppGlobals />
      {children}
    </GamutProvider>
  );
}
