import { useEffect, useState } from 'react';
import { Anchor, Box, FlexBox, Tab, TabList, TabPanel, TabPanels, Tabs } from '@codecademy/gamut';
import { filesApi, type DownloadKind, type FileItem } from '../api/files';
import { frameUrl } from '../files/versions';
import { t } from '../i18n/t';
import { useMediaQuery } from '../lib/useMediaQuery';

type ViewKind = 'translated' | 'original' | 'compare';

const FRAME_BORDER = {
  border: 1,
  borderStyle: 'solid',
  borderColor: 'border-secondary',
  borderRadius: 'md',
} as const;

function Frame({ item, kind }: { item: FileItem; kind: DownloadKind }) {
  const label = kind === 'original' ? t('viewer.original') : t('viewer.translated');
  return (
    <Box height="80vh" minHeight="480px" width="100%" overflow="hidden" {...FRAME_BORDER}>
      <iframe
        title={t('viewer.frameTitle', { name: item.filename, kind: label })}
        src={frameUrl(item, kind, null)}
        width="100%"
        height="100%"
        frameBorder={0}
      />
    </Box>
  );
}

/** Khung xem bản dịch HIỆN TẠI (tab Bản dịch / Bản gốc / So sánh). Bản cũ xem ở trang Phiên bản (`/files/:id/versions`). */
export function PdfViewer({ item }: { item: FileItem }) {
  const wide = useMediaQuery('(min-width: 1024px)');
  const [view, setView] = useState<ViewKind>('translated');

  // Nếu màn hình thu hẹp trong lúc đang ở "So sánh", quay về "Bản dịch" — tab đó không còn nữa.
  useEffect(() => {
    if (!wide && view === 'compare') setView('translated');
  }, [wide, view]);

  const activeView: ViewKind = view === 'compare' && !wide ? 'translated' : view;
  const openKind: DownloadKind = activeView === 'original' ? 'original' : 'translated';

  return (
    <FlexBox flexDirection="column" gap={12}>
      <Tabs selectedKey={activeView} onSelectionChange={(key) => setView(key as ViewKind)}>
        <TabList aria-label={t('viewer.switchView')}>
          <Tab id="translated">{t('viewer.translated')}</Tab>
          <Tab id="original">{t('viewer.original')}</Tab>
          {wide && <Tab id="compare">{t('viewer.compare')}</Tab>}
        </TabList>
        <TabPanels>
          <TabPanel id="translated">
            <Frame item={item} kind="translated" />
          </TabPanel>
          <TabPanel id="original">
            <Frame item={item} kind="original" />
          </TabPanel>
          {wide && (
            <TabPanel id="compare">
              <FlexBox gap={16} flexWrap="wrap">
                <Box flexGrow={1} minWidth="320px">
                  <Frame item={item} kind="original" />
                </Box>
                <Box flexGrow={1} minWidth="320px">
                  <Frame item={item} kind="translated" />
                </Box>
              </FlexBox>
            </TabPanel>
          )}
        </TabPanels>
      </Tabs>
      <Box>
        <Anchor href={filesApi.viewUrl(item.id, openKind)} target="_blank" rel="noopener noreferrer">
          {t('viewer.openNewTab')}
        </Anchor>
      </Box>
    </FlexBox>
  );
}
