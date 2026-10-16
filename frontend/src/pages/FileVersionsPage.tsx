import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Badge, Box, Dialog, FillButton, FlexBox, Text, Toggle } from '@codecademy/gamut';
import { toApiError, type ApiError } from '../api/client';
import { filesApi, isPending, type FileItem, type Meta } from '../api/files';
import { BreadcrumbBand } from '../components/BreadcrumbBand';
import { FilePlaceholder } from '../components/FilePlaceholder';
import { PageContainer } from '../components/PageContainer';
import { VersionTimeline } from '../components/VersionTimeline';
import { configRows, entriesOf, entryHeadline, frameUrl, languageNamer, type VersionEntry } from '../files/versions';
import { useFileItem } from '../files/useFileItem';
import { useMeta } from '../files/useMeta';
import { errorText, t } from '../i18n/t';
import { useMediaQuery } from '../lib/useMediaQuery';

const WIDE = '(min-width: 1024px)';

function Side({ item, entry, meta, side }: { item: FileItem; entry: VersionEntry | null; meta: Meta | null; side: 'left' | 'right' }) {
  if (!entry) {
    return <Text color="text-secondary" data-testid="left-empty">{t('versions.noPrevious')}</Text>;
  }
  return (
    <FlexBox flexDirection="column" gap={8} data-testid={`${side}-side`}>
      <Text as="h2" variant="title-xs">{entryHeadline(entry, meta)}</Text>
      {entry.available ? (
        <Box height="70vh" minHeight="420px" border={1} borderStyle="solid" borderColor="border-secondary" borderRadius="md" overflow="hidden">
          <iframe title={t('versions.frameTitle', { name: item.filename, n: entry.version_no })} src={frameUrl(item, 'translated', entry.id)}
            width="100%" height="100%" frameBorder={0} />
        </Box>
      ) : (
        <Alert type="notice" placement="inline">{t('detail.version.missing')}</Alert>
      )}
    </FlexBox>
  );
}

/** /files/:id/versions (spec 2026-10-15 §2, §9): thanh mốc theo version_no tăng dần, bản đang chọn bên PHẢI, bản ngay trước bên TRÁI
 *  (hoặc hai bản bất kỳ), một bảng cấu hình ba cột tô dòng khác nhau, hai PDF cạnh nhau (dọc khi hẹp), Khôi phục kiểu WordPress. */
export function FileVersionsPage() {
  const { id = '' } = useParams();
  return <VersionsView key={id} id={id} />; // key theo id: đổi tệp thì mọi lựa chọn/lỗi về mặc định
}

/** Khoá ổn định của một mốc (không phải chỉ số): bản hiện tại không có id. */
const keyOf = (entry: VersionEntry) => entry.id ?? 'current';

function VersionsView({ id }: { id: string }) {
  const navigate = useNavigate();
  const meta = useMeta();
  const wide = useMediaQuery(WIDE);
  const { item, setItem, error, load } = useFileItem(id);
  // Lựa chọn lưu theo khoá bản (id), không theo chỉ số: server tỉa bản cũ thì bên đã ghim không lặng lẽ trỏ sang bản khác.
  const [right, setRight] = useState<string | null>(null); // null = bản mới nhất (tới khi người dùng chọn)
  const [anyPair, setAnyPair] = useState(false);
  const [left, setLeft] = useState<string | null>(null); // chỉ có nghĩa khi anyPair; null = đi theo phải
  const [confirming, setConfirming] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<ApiError | null>(null);
  const pending = item ? isPending(item) : false;

  const entries = useMemo(() => (item ? entriesOf(item) : []), [item]);
  const last = entries.length - 1;
  const indexOf = (key: string | null) => (key === null ? -1 : entries.findIndex((entry) => keyOf(entry) === key));
  const pinnedRight = indexOf(right);
  // So sánh hai bản cần trái < phải: bản phải ít nhất là Bản thứ hai (nếu có từ hai bản trở lên).
  const rightIndex = Math.max(pinnedRight >= 0 ? pinnedRight : last, anyPair && last >= 1 ? 1 : 0); // bản đã ghim biến mất → về bản mới nhất
  const followLeft = rightIndex > 0 ? rightIndex - 1 : null;
  const pinnedLeft = indexOf(left);
  const leftIndex = anyPair && pinnedLeft >= 0 && pinnedLeft < rightIndex ? pinnedLeft : followLeft;
  const leftEntry = leftIndex === null ? null : entries[leftIndex];
  const rightEntry = entries[rightIndex];

  // So sánh hai bản (kiểu WordPress): kéo phải xuống tới trái thì ĐẨY trái xuống phải − 1; kéo trái lên tới phải thì kẹp ở phải − 1.
  const pickRight = (index: number) => {
    const next = Math.min(Math.max(index, anyPair ? 1 : 0), last);
    setRight(keyOf(entries[next]));
    if (anyPair && leftIndex !== null && next <= leftIndex) setLeft(keyOf(entries[next - 1]));
  };
  const pickLeft = (index: number) => setLeft(keyOf(entries[Math.min(Math.max(index, 0), rightIndex - 1)]));

  async function restore() {
    setConfirming(false); // đóng trước: lỗi hiện trên trang, không nằm sau hộp thoại
    if (!item || !rightEntry?.id || restoring) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      const next = await filesApi.restoreVersion(item.id, rightEntry.id);
      // Ghi cả vào bộ nhớ đệm: trang chi tiết hiện ngay "Đang khôi phục Bản K…" + "Phiên bản cũ (N)". Phản hồi 202 là to_item, KHÔNG có
      // `versions` → giữ danh sách đang có (K tra từ đó) tới khi trang chi tiết tự làm mới.
      setItem({ ...next, versions: next.versions ?? item.versions });
      navigate(`/files/${item.id}`);
    } catch (caught) {
      setRestoreError(toApiError(caught));
      setRestoring(false);
    }
  }

  // Tệp biến mất (xoá ở tab khác) trong lúc trang đang mở: lần hỏi lại trả 404 → như trang chi tiết, thay nội dung cũ bằng "không tìm thấy".
  if (!item || !rightEntry || error?.code === 'not_found') {
    return (
      <>
        <BreadcrumbBand />
        <FilePlaceholder error={error} onRetry={() => void load()} />
      </>
    );
  }

  const nameOf = languageNamer(meta);
  const rightRows = configRows(rightEntry, meta, nameOf);
  const leftRows = leftEntry ? configRows(leftEntry, meta, nameOf) : null;
  const canRestore = rightEntry.id !== null && rightEntry.available && !pending && !restoring;

  return (
    <>
    <BreadcrumbBand filename={item.filename} fileId={item.id} section={t('versions.crumb')} back={{ to: `/files/${item.id}`, tip: t('versions.back') }} />
    <PageContainer py={32}>
      <Text as="h1" variant="title-md">{t('versions.title')}</Text>
      <Text color="text-secondary" fontSize={14} mt={4}>{t('versions.note')}</Text>
      {pending && <Box mt={16}><Alert type="notice" placement="inline">{t('versions.pendingNotice')}</Alert></Box>}
      {restoreError && <Box mt={16}><Alert type="error" placement="inline">{errorText(restoreError.code, restoreError.params)}</Alert></Box>}
      <Box mt={16} aria-label={t('versions.timeline')} role="group">
        <VersionTimeline entries={entries} rightIndex={rightIndex} leftIndex={leftIndex} anyPair={anyPair} narrow={!wide}
          onRightChange={pickRight} onLeftChange={pickLeft} />
      </Box>
      <Box mt={12}>
        <Toggle as="input" label={t('versions.anyPair')} checked={anyPair} onChange={() => { setAnyPair((value) => !value); setLeft(null); }} />
      </Box>
      <FlexBox flexDirection={wide ? 'row' : 'column'} gap={16} mt={24} data-testid="sides">
        <Box flexGrow={1} minWidth={0} width={wide ? '50%' : '100%'}><Side item={item} entry={leftEntry} meta={meta} side="left" /></Box>
        <Box flexGrow={1} minWidth={0} width={wide ? '50%' : '100%'}>
          <Side item={item} entry={rightEntry} meta={meta} side="right" />
          {rightEntry.id !== null && (
            <Box mt={12}>
              <FillButton type="button" onClick={() => setConfirming(true)} disabled={!canRestore}>{t('restore.action')}</FillButton>
            </Box>
          )}
        </Box>
      </FlexBox>
      <Box mt={24}>
        <Text as="h2" variant="title-xs">{t('detail.config.title')}</Text>
        <Text fontSize={14} color="text-secondary" mt={4}>{t('detail.config.note')}</Text>
        <Box as="dl" m={0} mt={12} data-testid="config-compare">
          <FlexBox gap={8} py={4} flexWrap="wrap">
            <Box minWidth="160px" />
            <Box flexGrow={1} minWidth="200px">
              <Text fontSize={14} fontWeight="title">{leftEntry ? t('detail.version.label', { n: leftEntry.version_no }) : t('versions.noPrevious')}</Text>
            </Box>
            <Box flexGrow={1} minWidth="200px"><Text fontSize={14} fontWeight="title">{t('detail.version.label', { n: rightEntry.version_no })}</Text></Box>
          </FlexBox>
          {rightRows.map((row, index) => {
            const leftValue = leftRows ? leftRows[index].value : null;
            const differs = leftValue !== null && leftValue !== row.value;
            return (
              <FlexBox key={row.key} gap={8} py={4} px={differs ? 8 : 0} flexWrap="wrap" bg={differs ? 'background-selected' : undefined}
                data-differs={differs ? 'true' : undefined}>
                <Box as="dt" minWidth="160px"><Text fontSize={14} color="text-secondary">{row.label}</Text></Box>
                <Box as="dd" m={0} flexGrow={1} minWidth="200px"><Text fontSize={14}>{leftValue ?? t('detail.config.none')}</Text></Box>
                <Box as="dd" m={0} flexGrow={1} minWidth="200px">
                  <Text fontSize={14}>{row.value}</Text>
                  {differs && <> <Badge variant="accent" size="sm">{t('versions.differs')}</Badge></>}
                </Box>
              </FlexBox>
            );
          })}
        </Box>
      </Box>
      <Dialog isOpen={confirming} title={t('restore.title', { k: rightEntry.version_no })} onRequestClose={() => setConfirming(false)}
        confirmCta={{ children: t('restore.confirm'), onClick: () => void restore() }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setConfirming(false) }}>
        <FlexBox flexDirection="column" gap={8}>
          <Text>{t('restore.body', { k: rightEntry.version_no, n: item.version_no, next: item.version_no + 1 })}</Text>
          <Text fontSize={14} color="text-secondary">{t('restore.pruneNote')}</Text>
          {!rightEntry.has_tables && rightEntry.engine !== 'google_free' && (
            <Alert type="notice" placement="inline">{t('restore.noTables')}</Alert>
          )}
        </FlexBox>
      </Dialog>
    </PageContainer>
    </>
  );
}
