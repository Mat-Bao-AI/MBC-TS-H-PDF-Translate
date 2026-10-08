import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

export function renderApp(routes: ReactElement, { at = '/' }: { at?: string } = {}) {
  return render(
    <GamutProvider theme={theme}>
      <MemoryRouter initialEntries={[at]}>
        <AuthProvider>
          {routes}
          <LocationProbe />
        </AuthProvider>
      </MemoryRouter>
    </GamutProvider>,
  );
}
