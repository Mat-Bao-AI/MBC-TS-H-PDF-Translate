import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import styled from '@emotion/styled';
import {
  Alert, Box, Breadcrumbs, Dialog, FillButton, FlexBox, FormGroup, IconButton, ProgressBar, Select, StrokeButton, Text,
} from '@codecademy/gamut';
import { ArrowLeftIcon } from '@codecademy/gamut-icons';
import { toApiError, type ApiError } from '../api/client';
import { filesApi, hasTranslation, isPending, type FileItem, type Meta, type RetranslateChoice } from '../api/files';
import { PageContainer } from '../components/PageContainer';
import { PdfViewer } from '../components/PdfViewer';
import { RetranslateDialog } from '../components/RetranslateDialog';
import { RouterAnchor, useLinkClick } from '../components/RouterAnchor';
import { SkeletonCard } from '../components/SkeletonCard';
import { StatusBadge } from '../components/StatusBadge';
import { engineLabel } from '../files/engines';
import { fileCaption, fontLabel, fontOptions, otherProfile, retranslateCaption } from '../files/fonts';
import { useMeta } from '../files/useMeta';
import { errorText, t, type MessageKey } from '../i18n/t';
import { cacheClear, cacheGet, cacheSet } from '../lib/swrCache';

// Tên tệp dài liền một khối (không khoảng trắng) phải xuống dòng, không đẩy ngang trang trên điện thoại.
const FileTitle = styled(Text)({ minWidth: 0, overflowWrap: 'anywhere' });

const fileKey = (id: string) => `file:${id}`;
const SKELETON_DETAIL_HEIGHT = 900;

const FLOATING_TIP = { placement: 'floating' } as const;

/** Dải breadcrumb riêng ngay dưới thanh trên cùng: nút quay lại + đường dẫn "Tệp của tôi › tên tệp". */
function BreadcrumbBand({ filename }: { filename?: string }) {
  const goHome = useLinkClick('/');
  const crumbs = filename
    ? [{ title: t('home.myFiles'), href: '/', payload: '/' }, { title: filename }]
    : [{ title: t('home.myFiles'), href: '/', payload: '/' }];
  return (
    <Box data-testid="breadcrumb-band" bg="background-selected" borderBottom={1} borderColor="border-tertiary" py={8}>
      <PageContainer>
        <FlexBox alignItems="center" gap={8}>
          <IconButton icon={ArrowLeftIcon} tip={t('detail.back')} tipProps={FLOATING_TIP} href="/"
            onClick={goHome} size="small" variant="secondary" />
          <Box minWidth={0}>
            <Breadcrumbs crumbs={crumbs} onClick={(event) => goHome(event)} />
          </Box>
        </FlexBox>
      </PageContainer>
    </Box>
  );
}

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
  // Đã mở tệp này rồi thì hiện ngay bản cũ trong bộ nhớ đệm; `load` làm mới ngầm (không có khung trống rồi bật ra).
  const [item, setItemState] = useState<FileItem | null>(() => cacheGet<FileItem>(fileKey(id)) ?? null);
  const setItem = useCallback((next: FileItem | null) => {
    if (next) cacheSet(fileKey(next.id), next);
    setItemState(next);
  }, []);
  const [error, setError] = useState<ApiError | null>(null);
  const [retranslateOpen, setRetranslateOpen] = useState(false);
  const [sending, setSending] = useState(false); // POST dịch lại đang bay: khoá nút "Dịch lại"
  const sendingRef = useRef(false); // chống gửi đôi trước khi lượt render kế đặt lại `disabled`
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [choosingFont, setChoosingFont] = useState(false);
  const [rebuildFont, setRebuildFont] = useState('sans');
  const rebuilding = useRef(false);
  // Giữ id mới nhất: khi route chuyển sang /files/:id khác mà component không unmount,
  // một response đang bay cho id cũ phải bị bỏ qua thay vì ghi đè state của id mới.
  const currentId = useRef(id);
  currentId.current = id;

  const load = useCallback(
    () =>
      filesApi
        .get(id)
        .then((next) => { if (currentId.current !== id) return; setItem(next); setError(null); })
        .catch((caught) => { if (currentId.current !== id) return; setError(toApiError(caught)); }),
    [id, setItem],
  );

  useEffect(() => {
    setItem(cacheGet<FileItem>(fileKey(id)) ?? null);
    setError(null);
    setSending(false);
    sendingRef.current = false;
    setRetranslateOpen(false);
    setConfirmingDelete(false);
    setChoosingFont(false);
    void load();
  }, [load, id, setItem]);

  const pending = item ? isPending(item) : false;
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => { void load(); }, 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  async function retranslate(choice: RetranslateChoice | null) {
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
      cacheClear(fileKey(id));
      cacheClear('files:'); // danh sách ở trang chủ không được còn hiện tệp vừa xoá
      navigate('/', { replace: true });
    } catch (caught) {
      if (currentId.current === id) setError(toApiError(caught));
    }
  }

  if (error?.code === 'not_found') {
    return (
      <>
        <BreadcrumbBand />
        <PageContainer py={32}>
          <FlexBox flexDirection="column" gap={16}>
            <Alert type="error" placement="inline">{t('detail.notFound')}</Alert>
            <RouterAnchor to="/">{t('common.backHome')}</RouterAnchor>
          </FlexBox>
        </PageContainer>
      </>
    );
  }
  if (!item) {
    return (
      <>
        <BreadcrumbBand />
        <PageContainer py={32}>
          {error ? (
            <Alert type="error" placement="inline" cta={{ text: t('common.retry'), onClick: () => void load() }}>
              {errorText(error.code, error.params)}
            </Alert>
          ) : (
            <SkeletonCard height={SKELETON_DETAIL_HEIGHT} />
          )}
        </PageContainer>
      </>
    );
  }

  const nameOf = (code: string) => meta?.languages.find((language) => language.code === code)?.name ?? code;
  const pct = item.total_pages ? Math.round((item.done_pages * 100) / item.total_pages) : 0;
  const caption = fileCaption(item, nameOf(item.language), meta); // bản cũ — kể cả lúc đang dịch lại
  const translated = hasTranslation(item);
  // Bản cũ đang được thay (dựng lại font HOẶC dịch lại từ đầu): tệp queued/running nhưng bản dịch cũ còn nguyên.
  const replacing = item.rebuilding || item.retranslating;
  const canRetranslate = (item.status === 'done' || item.status === 'error') && !replacing;
  const replacingText = item.retranslate_to
    ? t('retranslate.running', { target: retranslateCaption(item.retranslate_to, nameOf(item.retranslate_to.language), meta) })
    : t('rebuild.running', { font: fontLabel(item.rebuild_font ?? '') });

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
        <StrokeButton onClick={() => setConfirmingDelete(true)} disabled={item.status === 'running'}>
          {t('action.delete')}
        </StrokeButton>
      </FlexBox>
      <Box mt={24}>
        {replacing && (
          <FlexBox flexDirection="column" gap={16}>
            <Alert type="notice" placement="inline">{replacingText}</Alert>
            {item.status === 'queued' && <Text>{t('detail.waiting')}</Text>}
            {item.status === 'running' && (
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
              // Câu chung cho dựng lại và dịch lại (một cột rebuild_error, không phân biệt loại — spec §7, §10).
              <Alert type="error" placement="inline">
                {t('rebuild.failed', { reason: withoutFinalStop(item.rebuild_error) })}
              </Alert>
            )}
            {item.untranslated > 0 && (
              <Alert type="notice" placement="inline">{t('detail.untranslated', { count: item.untranslated })}</Alert>
            )}
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
