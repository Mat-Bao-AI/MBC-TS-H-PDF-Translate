import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { t } from '../i18n/t';
import { renderApp } from '../test/render';
import { BreadcrumbBand } from './BreadcrumbBand';

function renderBand(band: React.ReactElement) {
  renderApp(
    <Routes>
      <Route path="/" element={<p>trang chính</p>} />
      <Route path="/files/:id" element={<p>trang tệp</p>} />
      <Route path="/start" element={band} />
    </Routes>,
    { at: '/start' },
  );
}
const crumbs = () => within(screen.getByRole('navigation', { name: 'breadcrumbs' }));

describe('BreadcrumbBand', () => {
  it('defaults to "Tệp của tôi › tên tệp" with the back arrow going home', async () => {
    renderBand(<BreadcrumbBand filename="Báo cáo.pdf" />);
    const user = userEvent.setup();
    expect(crumbs().getByText('Báo cáo.pdf')).toBeInTheDocument();
    expect(crumbs().queryByRole('link', { name: 'Báo cáo.pdf' })).toBeNull();
    await user.click(screen.getByRole('link', { name: t('detail.back') }));
    expect(screen.getByText('trang chính')).toBeInTheDocument();
  });

  it('with a section turns the file name into a link to the file, ends on the section without navigating, and honours `back`', async () => {
    renderBand(<BreadcrumbBand filename="Báo cáo.pdf" fileId="f00000000001" section={t('versions.crumb')} back={{ to: '/files/f00000000001', tip: t('versions.back') }} />);
    const user = userEvent.setup();
    expect(crumbs().getByRole('link', { name: 'Báo cáo.pdf' })).toHaveAttribute('href', '/files/f00000000001');
    expect(screen.getByRole('link', { name: t('versions.back') })).toHaveAttribute('href', '/files/f00000000001');
    await user.click(crumbs().getByText(t('versions.crumb'))); // mẩu cuối không có href
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/start$/);
    await user.click(crumbs().getByRole('link', { name: 'Báo cáo.pdf' }));
    expect(screen.getByText('trang tệp')).toBeInTheDocument();
  });

  it('leaves modified clicks to the browser instead of navigating', async () => {
    renderBand(<BreadcrumbBand filename="Báo cáo.pdf" fileId="f00000000001" section={t('versions.crumb')} />);
    const user = userEvent.setup();
    await user.keyboard('{Control>}');
    await user.click(crumbs().getByRole('link', { name: 'Báo cáo.pdf' }));
    await user.keyboard('{/Control}');
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/start$/);
  });
});
