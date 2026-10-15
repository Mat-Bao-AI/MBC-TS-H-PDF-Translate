import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import styled from '@emotion/styled';
import {
  Alert, Box, Dialog, Disclosure, FillButton, FlexBox, FormGroup, ProgressBar, Select, StrokeButton, Text,
} from '@codecademy/gamut';
import { toApiError } from '../api/client';
import { filesApi, hasTranslation, type FileItem, type Meta, type RetranslateRequest } from '../api/files';
import { BreadcrumbBand } from '../components/BreadcrumbBand';
import { FilePlaceholder } from '../components/FilePlaceholder';
import { PageContainer } from '../components/PageContainer';
import { PdfViewer } from '../components/PdfViewer';
import { RetranslateDialog } from '../components/RetranslateDialog';
import { useLinkClick } from '../components/RouterAnchor';
import { StatusBadge } from '../components/StatusBadge';
import { engineLabel } from '../files/engines';
import { fileCaption, fontLabel, fontOptions, otherProfile, retranslateCaption } from '../files/fonts';
import { snapshotProfileName } from '../files/profiles';
import { configRows, currentEntry, fileCacheKey, languageNamer } from '../files/versions';
import { useFileItem } from '../files/useFileItem';
import { useMeta } from '../files/useMeta';
import { errorText, t, type MessageKey } from '../i18n/t';
import { cacheClear } from '../lib/swrCache';

// Tên tệp dài liền một khối (không khoảng trắng) phải xuống dòng, không đẩy ngang trang trên điện thoại.
const FileTitle = styled(Text)({ minWidth: 0, overflowWrap: 'anywhere' });

const STAGES = ['split', 'translate', 'render'] as const;
type Stage = (typeof STAGES)[number];

/** "…: <lý do>. Vẫn giữ…" — bỏ dấu chấm cuối của lý do để không thành hai dấu chấm. */
const withoutFinalStop = (text: string) => text.trim().replace(/[.。]+$/, '');

function runningText(item: FileItem, meta: Meta | null): string {
  const stage = STAGES.find((candidate) => candidate === item.stage) as Stage | undefined;
  if (stage) {
    // Dịch lại từ đầu: bước dịch chạy bằng engine MỚI (retranslate_to); dòng mô tả của tệp vẫn là bản cũ.
    const engine = item.retranslate_to?.engine ?? item.engine;
    const head = t(`detail.stage.${stage}` as MessageKey, { engine: engineLabel(engine, meta?.engines) });
    return item.total_pages ? `${head} ${t('detail.stageProgress', { done: item.done_pages, total: item.total_pages })}` : head;
  }
  return item.total_pages ? t('detail.progress', { done: item.done_pages, total: item.total_pages }) : t('detail.starting');
}

export function FileDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const meta = useMeta();
  const versionsHref = `/files/${id}/versions`;
  const goVersions = useLinkClick(versionsHref);
  const { item, setItem, error, setError, load, currentId } = useFileItem(id);
  const [retranslateOpen, setRetranslateOpen] = useState(false);
  const [sending, setSending] = useState(false); // POST dịch lại đang bay: khoá nút "Dịch lại"
  const sendingRef = useRef(false); // chống gửi đôi trước khi lượt render kế đặt lại `disabled`
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [choosingFont, setChoosingFont] = useState(false);
  const [rebuildFont, setRebuildFont] = useState('sans');
  const rebuilding = useRef(false);
  useEffect(() => {
    setSending(false);
    sendingRef.current = false;
    setRetranslateOpen(false);
    setConfirmingDelete(false);
    setChoosingFont(false);
  }, [id]);

  async function retranslate(choice: RetranslateRequest | null) {
    if (!choice || sendingRef.current) return; // hộp đơn luôn trả lựa chọn; ref chặn gửi đôi
    sendingRef.current = true;
    setSending(true);
    setError(null); // lý do của lượt bị từ chối trước không được nằm dưới một lượt mới
    const sentFor = id;
    try {
      const next = await filesApi.retranslate(sentFor, choice);
      if (currentId.current === sentFor) setItem(next); // queued → vòng hỏi tiến độ 2 s tự chạy
    } catch (caught) {
      if (currentId.current === sentFor) setError(toApiError(caught));
    } finally {
      if (currentId.current === sentFor) { // đã sang tệp khác: effect đổi id đã đặt lại
        sendingRef.current = false;
        setSending(false);
      }
    }
  }

  function openRebuild(fontUsed: string | null) {
    setRebuildFont(otherProfile(fontUsed));
    setChoosingFont(true);
  }

  async function rebuild() {
    setChoosingFont(false); // đóng trước: thông báo dựng lại / lỗi hiện trên trang, không nằm sau hộp thoại
    if (rebuilding.current) return; // chống gửi đôi khi POST còn đang bay
    rebuilding.current = true;
    try {
      const next = await filesApi.rebuild(id, rebuildFont);
      if (currentId.current === id) setItem(next); // queued → vòng hỏi tiến độ 2 s tự chạy lại
    } catch (caught) {
      if (currentId.current === id) setError(toApiError(caught));
    } finally {
      rebuilding.current = false;
    }
  }

  async function remove() {
    setConfirmingDelete(false);
    try {
      await filesApi.remove(id);
      cacheClear(fileCacheKey(id));
      cacheClear('files:'); // danh sách ở trang chủ không được còn hiện tệp vừa xoá
      navigate('/', { replace: true });
    } catch (caught) {
      if (currentId.current === id) setError(toApiError(caught));
    }
  }

  if (!item || error?.code === 'not_found') {
    return (
      <>
        <BreadcrumbBand />
        <FilePlaceholder error={error} onRetry={() => void load()} />
      </>
    );
  }

  const nameOf = languageNamer(meta);
  const pct = item.total_pages ? Math.round((item.done_pages * 100) / item.total_pages) : 0;
  const oldVersions = item.versions?.length ?? 0;
  const caption = [
    fileCaption(item, nameOf(item.language), meta), // bản cũ — kể cả lúc đang dịch lại / khôi phục
    item.version_no > 1 || oldVersions > 0 ? t('file.version', { n: item.version_no }) : null,
    snapshotProfileName(item.config),
    item.restored_from !== null ? t('detail.restoredFrom', { k: item.restored_from }) : null,
  ].filter(Boolean).join(' · ');
  const translated = hasTranslation(item);
  // Bản cũ đang được thay (dựng lại font HOẶC dịch lại từ đầu HOẶC khôi phục): tệp queued/running nhưng bản dịch cũ còn nguyên.
  const replacing = item.rebuilding || item.retranslating;
  const canRetranslate = (item.status === 'done' || item.status === 'error') && !replacing;
  const restoringFrom = item.versions?.find((version) => version.id === item.restore_version)?.version_no;
  const replacingText = item.restoring
    ? (restoringFrom === undefined ? t('restore.runningUnknown') : t('restore.running', { k: restoringFrom }))
    : item.retranslate_to
      ? t('retranslate.running', { target: retranslateCaption(item.retranslate_to, nameOf(item.retranslate_to.language), meta) })
      : t('rebuild.running', { font: fontLabel(item.rebuild_font ?? '') });
  const currentRows = configRows(currentEntry(item), meta, nameOf);

  return (
    <>
    <BreadcrumbBand filename={item.filename} />
    <PageContainer py={32}>
      <FlexBox gap={12} alignItems="center" flexWrap="wrap">
        <FileTitle as="h1" variant="title-md" title={item.filename} truncate="ellipsis" truncateLines={2}>
          {item.filename}
        </FileTitle>
        <StatusBadge item={item} />
      </FlexBox>
      <Text color="text-secondary" fontSize={14} mt={4}>{caption}</Text>
      <FlexBox gap={12} flexWrap="wrap" mt={16}>
        {translated && (
          <>
            <FillButton href={filesApi.downloadUrl(item.id, 'translated')}>{t('action.downloadTranslated')}</FillButton>
            <StrokeButton href={filesApi.downloadUrl(item.id, 'original')}>{t('action.downloadOriginal')}</StrokeButton>
          </>
        )}
        {canRetranslate && (
          <StrokeButton onClick={() => setRetranslateOpen(true)} disabled={sending}>{t('action.retranslate')}</StrokeButton>
        )}
        {item.status === 'done' && !replacing && (
          <StrokeButton onClick={() => openRebuild(item.font_used)}>{t('rebuild.action')}</StrokeButton>
        )}
        {oldVersions > 0 && (
          <StrokeButton href={versionsHref} onClick={goVersions}>{t('detail.versionsButton', { n: oldVersions })}</StrokeButton>
        )}
        <StrokeButton onClick={() => setConfirmingDelete(true)} disabled={item.status === 'running'}>
          {t('action.delete')}
        </StrokeButton>
      </FlexBox>
      <Box mt={24}>
        {replacing && (
          <FlexBox flexDirection="column" gap={16}>
            <Alert type="notice" placement="inline">{replacingText}</Alert>
            {/* Khôi phục xong trong chớp mắt, không có bước/trang để báo — chỉ dải thông báo. */}
            {item.status === 'queued' && !item.restoring && <Text>{t('detail.waiting')}</Text>}
            {item.status === 'running' && !item.restoring && (
              <Box>
                <ProgressBar percent={pct} variant="blue" size="large" minimumPercent={2} />
                <Text mt={8} color="text-secondary">{runningText(item, meta)}</Text>
              </Box>
            )}
            <PdfViewer item={item} />
          </FlexBox>
        )}
        {!replacing && item.status === 'queued' && <Text>{t('detail.waiting')}</Text>}
        {!replacing && item.status === 'running' && (
          <>
            <ProgressBar percent={pct} variant="blue" size="large" minimumPercent={2} />
            <Text mt={8} color="text-secondary">{runningText(item, meta)}</Text>
          </>
        )}
        {item.status === 'done' && !replacing && (
          <FlexBox flexDirection="column" gap={16}>
            <Alert type="success" placement="inline">{t('detail.done')}</Alert>
            {item.rebuild_error && (
              // Câu chung cho dựng lại, dịch lại và khôi phục (một cột rebuild_error, không phân biệt loại).
              <Alert type="error" placement="inline">
                {t('rebuild.failed', { reason: withoutFinalStop(item.rebuild_error) })}
              </Alert>
            )}
            {item.untranslated > 0 && (
              <Alert type="notice" placement="inline">{t('detail.untranslated', { count: item.untranslated })}</Alert>
            )}
            <Disclosure heading={t('detail.currentConfig')} headingLevel="h3" spacing="compact" body={(
              <Box as="dl" data-testid="current-config" m={0}>
                {currentRows.map((row) => (
                  <FlexBox key={row.key} gap={8} py={4} flexWrap="wrap">
                    <Box as="dt" minWidth="160px"><Text fontSize={14} color="text-secondary">{row.label}</Text></Box>
                    <Box as="dd" m={0}><Text fontSize={14}>{row.value}</Text></Box>
                  </FlexBox>
                ))}
              </Box>
            )} />
            <PdfViewer item={item} />
          </FlexBox>
        )}
        {item.status === 'error' && (
          <Alert type="error" placement="inline">
            <strong>{t('detail.error')}</strong>: {item.message}
          </Alert>
        )}
        {error && (
          <Box mt={16}>
            <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>
          </Box>
        )}
      </Box>
      <Dialog
        isOpen={confirmingDelete}
        title={t('delete.title')}
        variant="danger"
        onRequestClose={() => setConfirmingDelete(false)}
        confirmCta={{ children: t('delete.confirm'), onClick: () => void remove() }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setConfirmingDelete(false) }}
      >
        {t('delete.body', { name: item.filename })}
      </Dialog>
      <Dialog
        isOpen={choosingFont}
        title={t('rebuild.title')}
        onRequestClose={() => setChoosingFont(false)}
        confirmCta={{ children: t('rebuild.confirm'), onClick: () => void rebuild() }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setChoosingFont(false) }}
      >
        <FlexBox flexDirection="column" gap={16}>
          <Text>{t('rebuild.body')}</Text>
          <FormGroup label={t('font.field')} htmlFor="rebuild-font" isSoloField>
            <Select id="rebuild-font" defaultValue={rebuildFont} options={fontOptions()}
              onChange={(event) => setRebuildFont(event.target.value)} />
          </FormGroup>
        </FlexBox>
      </Dialog>
      <RetranslateDialog target={retranslateOpen ? { item } : null} onClose={() => setRetranslateOpen(false)}
        onConfirm={(choice) => void retranslate(choice)} />
    </PageContainer>
    </>
  );
}
