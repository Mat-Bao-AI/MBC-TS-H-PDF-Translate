import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Anchor, Box, Dialog, FillButton, FlexBox, Input, Pagination, StrokeButton, Text } from '@codecademy/gamut';
import { PdfIcon, SearchIcon } from '@codecademy/gamut-icons';
import { toApiError } from '../api/client';
import {
  PAGE_SIZE, filesApi, type BulkRetranslateResult, type BulkSelection, type FileItem, type RetranslateChoice, type SortDir, type SortKey,
} from '../api/files';
import { useAuth } from '../auth/AuthContext';
import { shortName } from '../auth/identity';
import { HeroDropZone } from '../components/HeroDropZone';
import { PageContainer } from '../components/PageContainer';
import { FileTable, type TableSort } from '../components/FileTable';
import { RetranslateDialog, type RetranslateTarget } from '../components/RetranslateDialog';
import { UploadModal } from '../components/UploadModal';
import { useFilePage } from '../files/useFilePage';
import { useMeta } from '../files/useMeta';
import { errorText, t } from '../i18n/t';

function EmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <FlexBox flexDirection="column" alignItems="center" gap={12} py={64} textAlign="center">
      <PdfIcon size={48} color="text-secondary" aria-hidden />
      <Text as="h3" variant="title-xs">{t('home.empty.title')}</Text>
      <Text color="text-secondary">{t('home.empty.body')}</Text>
      <FillButton onClick={onUpload}>{t('home.upload')}</FillButton>
    </FlexBox>
  );
}

function NoMatch({ q, onClear }: { q: string; onClear: () => void }) {
  return (
    <FlexBox flexDirection="column" alignItems="center" gap={12} py={48} textAlign="center">
      <Text>{t('home.noMatch', { q })}</Text>
      <StrokeButton onClick={onClear}>{t('home.clearFilter')}</StrokeButton>
    </FlexBox>
  );
}

const SORT_KEYS: readonly SortKey[] = ['created', 'name', 'status'];
const sameSort = (a: TableSort, b: TableSort) => a?.key === b?.key && a?.dir === b?.dir;

function parseSort(params: URLSearchParams): TableSort {
  const key = SORT_KEYS.find((candidate) => candidate === params.get('sort'));
  if (!key) return null; // không có / rác = mặc định (created desc, không có mũi tên trên tiêu đề)
  const dir: SortDir = params.get('dir') === 'asc' ? 'asc' : 'desc';
  return { key, dir };
}

/** "Đã xếp hàng 3 tệp. Bỏ qua 1 tệp đang chờ/đang dịch. 22 tệp vượt hạn chờ (3 tệp/người) — đợi rồi chọn lại." */
function retranslateNotice(result: BulkRetranslateResult): string {
  return t('retranslate.queued', { queued: result.queued })
    + (result.skipped_pending > 0 ? t('retranslate.skippedPending', { skipped: result.skipped_pending }) : '')
    + (result.skipped_limit > 0 ? t('retranslate.skippedLimit', { skipped: result.skipped_limit, limit: result.limit }) : '');
}

export function HomePage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const page = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1);
  const sort = useMemo(() => parseSort(params), [params]);
  const { data, error, loading, reload } = useFilePage(q, page, sort?.key, sort?.dir);
  const [filter, setFilter] = useState(q);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [toDelete, setToDelete] = useState<FileItem | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Chọn dòng: id trong trang hiện tại; `allMatching` = mọi tệp khớp bộ lọc (kể cả trang khác).
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [allMatching, setAllMatching] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const bulkRunning = useRef(false);
  const [retranslateTarget, setRetranslateTarget] = useState<RetranslateTarget | null>(null);

  const setQuery = useCallback((nextQ: string, nextPage: number, replace: boolean, nextSort: TableSort = sort) => {
    // Gamut's Pagination re-syncs its controlled `pageNumber` through a `useMemo` that fires
    // during its own render (not an effect), so it calls `onChange` again with the same page
    // right after we navigate — skip the no-op or that second call updates the router while
    // Pagination is still rendering (dev warning) and pushes a duplicate history entry.
    if (nextQ === q && nextPage === page && sameSort(nextSort, sort)) return;
    const next = new URLSearchParams();
    if (nextQ) next.set('q', nextQ);
    if (nextSort) {
      next.set('sort', nextSort.key);
      next.set('dir', nextSort.dir);
    }
    if (nextPage > 1) next.set('page', String(nextPage));
    setParams(next, { replace });
  }, [q, page, sort, setParams]);

  const clearSelection = useCallback(() => {
    setSelectedIds([]);
    setAllMatching(false);
  }, []);

  useEffect(() => {
    clearSelection();
  }, [q, page, sort?.key, sort?.dir, clearSelection]);

  // Làm mới 3 giây một lần: giữ lựa chọn theo id, bỏ id không còn trong trang.
  useEffect(() => {
    if (!data) return;
    const present = new Set(data.items.map((item) => item.id));
    setSelectedIds((current) => (current.every((id) => present.has(id)) ? current : current.filter((id) => present.has(id))));
    if (data.total === 0) setAllMatching(false);
  }, [data]);

  useEffect(() => {
    setFilter(q);
  }, [q]);

  useEffect(() => {
    const wanted = filter.trim();
    if (wanted === q) return;
    const timer = window.setTimeout(() => setQuery(wanted, 1, true), 300);
    return () => window.clearTimeout(timer);
  }, [filter, q, setQuery]);

  const lastPage = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  useEffect(() => {
    if (data && page > lastPage) setQuery(q, lastPage, true);
  }, [data, page, lastPage, q, setQuery]);

  const languageNames = useMemo(
    () => Object.fromEntries((meta?.languages ?? []).map((language) => [language.code, language.name])),
    [meta],
  );

  async function runAction(action: () => Promise<unknown>) {
    setActionError(null);
    try {
      await action();
      reload();
    } catch (caught) {
      const apiError = toApiError(caught);
      setActionError(errorText(apiError.code, apiError.params));
    }
  }

  function confirmDelete() {
    if (!toDelete) return;
    const target = toDelete;
    setToDelete(null);
    void runAction(() => filesApi.remove(target.id));
  }

  const items = data?.items ?? [];
  const pageIds = items.map((item) => item.id);
  const selected = allMatching ? pageIds : selectedIds;
  const pageSelected = items.length > 0 && selected.length === items.length;
  const selectedCount = allMatching ? data?.total ?? 0 : selectedIds.length;

  function toggleRow(id: string) {
    setAllMatching(false);
    setSelectedIds(selected.includes(id) ? selected.filter((other) => other !== id) : [...selected, id]);
  }

  function togglePage() {
    setAllMatching(false);
    setSelectedIds(pageSelected ? [] : pageIds);
  }

  async function confirmBulkDelete() {
    if (bulkRunning.current) return; // chống bấm đúp
    bulkRunning.current = true;
    setBulkOpen(false);
    setActionError(null);
    setNotice(null);
    try {
      const result = await filesApi.bulkDelete(allMatching ? { all: true, q } : { ids: selectedIds });
      clearSelection();
      setNotice(t('bulk.done', { deleted: result.deleted })
        + (result.skipped_running > 0 ? t('bulk.skipped', { skipped: result.skipped_running }) : ''));
      reload();
    } catch (caught) {
      const apiError = toApiError(caught);
      setActionError(errorText(apiError.code, apiError.params));
    } finally {
      bulkRunning.current = false;
    }
  }

  async function confirmRetranslate(target: RetranslateTarget, settings: RetranslateChoice | null) {
    if (bulkRunning.current) return; // chống bấm đúp — dùng chung cờ với xoá hàng loạt
    bulkRunning.current = true;
    setActionError(null);
    setNotice(null);
    try {
      if ('item' in target) {
        if (settings) await filesApi.retranslate(target.item.id, settings); // hộp đơn luôn trả đủ bốn lựa chọn
      } else {
        const selection: BulkSelection = allMatching ? { all: true, q } : { ids: selectedIds };
        const result = await filesApi.bulkRetranslate({ ...selection, settings });
        clearSelection();
        setNotice(retranslateNotice(result));
      }
      reload();
    } catch (caught) {
      const apiError = toApiError(caught);
      setActionError(errorText(apiError.code, apiError.params)); // lỗi hàng loạt: giữ lựa chọn để thử lại
      // Dòng đơn bị từ chối (409 đang chờ/chạy, 429 hạn chờ): nạp lại để dòng hiện đúng trạng thái thật.
      if ('item' in target) reload();
    } finally {
      bulkRunning.current = false;
    }
  }

  const name = user ? shortName(user) : '';
  const openUpload = () => { setUploadFile(null); setUploadOpen(true); };

  return (
    <Box>
      <Box bg="background-selected" py={48}>
        <PageContainer>
          <FlexBox flexDirection="column" alignItems="center" gap={24}>
            <Text as="h1" variant="title-lg" textAlign="center">{t('home.greeting', { name })}</Text>
            <Box width="100%" maxWidth="720px">
              <HeroDropZone meta={meta} onFile={(file) => { setUploadFile(file); setUploadOpen(true); }} />
            </Box>
          </FlexBox>
        </PageContainer>
      </Box>
      <PageContainer py={32}>
        <FlexBox justifyContent="space-between" alignItems="center" gap={16} flexWrap="wrap" mb={16}>
          <Text as="h2" variant="title-sm">{t('home.myFiles')}</Text>
          <Box width="100%" maxWidth="320px">
            <Input id="file-filter" aria-label={t('home.filter')} placeholder={t('home.filter')} icon={SearchIcon}
              size="small" value={filter} onChange={(event) => { setFilter(event.target.value); setNotice(null); }} />
          </Box>
        </FlexBox>
        {actionError && (
          <Box mb={16}>
            <Alert type="error" placement="inline" onClose={() => setActionError(null)}>{actionError}</Alert>
          </Box>
        )}
        {notice && (
          <Box mb={16}>
            <Box role="status">
              <Alert type="success" placement="inline" onClose={() => setNotice(null)}>{notice}</Alert>
            </Box>
          </Box>
        )}
        {error ? (
          <Alert type="error" placement="inline" cta={{ text: t('common.retry'), onClick: reload }}>
            {t('home.loadError')}
          </Alert>
        ) : data && data.total === 0 && !q ? (
          <EmptyState onUpload={openUpload} />
        ) : data && data.total === 0 ? (
          <NoMatch q={q} onClear={() => { setFilter(''); setQuery('', 1, false); }} />
        ) : (
          <>
            {/* Vùng thông báo luôn có mặt trong DOM: nội dung đổi mới được đọc ra (mount kèm nội dung thì không). */}
            <Text screenreader role="status">
              {selectedCount > 0
                ? (allMatching ? t('home.selectedAll', { total: selectedCount }) : t('home.selected', { n: selectedCount }))
                : ''}
            </Text>
            {selectedCount > 0 && (
              <FlexBox role="group" aria-label={t('home.selectionBar')} alignItems="center" gap={12} flexWrap="wrap" mb={12}>
                <Text as="span" fontWeight="title">
                  {allMatching ? t('home.selectedAll', { total: selectedCount }) : t('home.selected', { n: selectedCount })}
                </Text>
                {pageSelected && !allMatching && data && data.total > items.length && (
                  <Anchor variant="inline" onClick={() => setAllMatching(true)}>
                    {t('home.selectAllMatching', { total: data.total })}
                  </Anchor>
                )}
                <FillButton size="small" variant="danger" onClick={() => setBulkOpen(true)}>{t('action.delete')}</FillButton>
                <StrokeButton size="small" onClick={() => setRetranslateTarget({ count: selectedCount })}>
                  {t('action.retranslate')}
                </StrokeButton>
                <StrokeButton size="small" onClick={clearSelection}>{t('home.clearSelection')}</StrokeButton>
              </FlexBox>
            )}
            <FileTable
              items={items}
              loading={loading && !data}
              languageNames={languageNames}
              meta={meta}
              selected={selected}
              sort={sort}
              onToggleRow={toggleRow}
              onTogglePage={togglePage}
              onSort={(key, dir) => { setNotice(null); setQuery(q, 1, false, dir === 'none' ? null : { key, dir }); }}
              onDelete={setToDelete}
              onRetranslate={(item) => setRetranslateTarget({ item })}
              onView={(item) => navigate(`/files/${item.id}`)}
            />
            {data && data.total > 0 && (
              <Text as="p" fontSize={14} color="text-secondary" mt={12} textAlign="center">
                {t('home.range', {
                  from: (page - 1) * PAGE_SIZE + 1,
                  to: Math.min((page - 1) * PAGE_SIZE + items.length, data.total),
                  total: data.total,
                })}
              </Text>
            )}
            {lastPage > 1 && page <= lastPage && (
              // N.b. gate on `page <= lastPage` too (not just `lastPage > 1`): Pagination re-syncs
              // through a `useMemo` that calls `onChange` once on mount, during its own render — if it
              // mounted while `page` is still out of range (before the redirect effect above corrects
              // the URL), that call would fire with a page different from the still-stale `page`, which
              // updates the router mid-render. Waiting until `page` is already valid keeps that initial
              // sync call a no-op (see the guard in `setQuery`).
              <FlexBox justifyContent="center" mt={24}>
                <Pagination totalPages={lastPage} pageNumber={Math.min(page, lastPage)}
                  onChange={(next) => { setNotice(null); setQuery(q, next, false); }} />
              </FlexBox>
            )}
          </>
        )}
      </PageContainer>
      <UploadModal isOpen={uploadOpen} initialFile={uploadFile} onClose={() => { setUploadOpen(false); setUploadFile(null); }}
        onUploaded={(item) => navigate(`/files/${item.id}`)} />
      <Dialog
        isOpen={toDelete !== null}
        title={t('delete.title')}
        variant="danger"
        onRequestClose={() => setToDelete(null)}
        confirmCta={{ children: t('delete.confirm'), onClick: confirmDelete }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setToDelete(null) }}
      >
        {toDelete ? t('delete.body', { name: toDelete.filename }) : null}
      </Dialog>
      <Dialog
        isOpen={bulkOpen}
        title={t('bulk.title', { n: selectedCount })}
        variant="danger"
        onRequestClose={() => setBulkOpen(false)}
        confirmCta={{ children: t('delete.confirm'), onClick: () => void confirmBulkDelete() }}
        cancelCta={{ children: t('common.cancel'), onClick: () => setBulkOpen(false) }}
      >
        {t('bulk.body')}
      </Dialog>
      <RetranslateDialog
        target={retranslateTarget}
        onClose={() => setRetranslateTarget(null)}
        // Gamut gọi onClose trước: `retranslateTarget` ở đây là giá trị của lượt render đang mở hộp.
        onConfirm={(settings) => { if (retranslateTarget) void confirmRetranslate(retranslateTarget, settings); }}
      />
    </Box>
  );
}
