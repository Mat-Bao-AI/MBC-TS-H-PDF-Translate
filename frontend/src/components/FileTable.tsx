import styled from '@emotion/styled';
import { Box, FlexBox, IconButton, Text } from '@codecademy/gamut';
// Deep import: gói không xuất DataGrid ở gốc, DataTable không chọn dòng, DataList không có kiểu bảng (test DataGrid.test.ts canh việc này khi nâng Gamut).
import { DataGrid } from '@codecademy/gamut/dist/DataList/DataGrid';
import type { OnQueryChange, Query } from '@codecademy/gamut';
import { breakpoints } from '@codecademy/gamut-styles';
import { DownloadIcon, FileDownloadIcon, PdfIcon, RedoIcon, TrashIcon, ViewIcon } from '@codecademy/gamut-icons';
import { useLayoutEffect, useRef, type ComponentProps, type MouseEvent, type ReactNode } from 'react';
import { filesApi, hasTranslation, isPending, type FileItem, type Meta, type SortDir, type SortKey } from '../api/files';
import { fileCaption } from '../files/fonts';
import { t } from '../i18n/t';
import { formatRelative } from '../lib/relativeTime';
import { RouterAnchor } from './RouterAnchor';
import { StatusBadge } from './StatusBadge';

// FloatingTip render qua portal ra ngoài bảng — tip mặc định (inline) bị ô TD (overflow: hidden)
// cắt mất phần thân, chỉ còn mũi tên nhỏ hiện ra (bug người dùng báo cáo).
const FLOATING_TIP = { placement: 'floating' } as const;

// Lý do không có bản dịch (hiện trong tooltip của icon bị khoá).
const noTranslationReason = (item: FileItem) =>
  item.status === 'error' ? t('action.noTranslation.error') : t('action.noTranslation.pending');

// Cột của bảng (key theo hàng) ↔ khoá sort của API.
const SORT_OF_COLUMN = { filename: 'name', created_at: 'created', status: 'status' } as const;
type SortColumn = keyof typeof SORT_OF_COLUMN;
const COLUMN_OF_SORT: Record<SortKey, SortColumn> = { name: 'filename', created: 'created_at', status: 'status' };
const isSortColumn = (key: unknown): key is SortColumn => typeof key === 'string' && key in SORT_OF_COLUMN;

export type TableSort = { key: SortKey; dir: SortDir } | null;

type Props = {
  items: FileItem[];
  loading: boolean;
  languageNames: Record<string, string>;
  meta: Meta | null;
  selected: string[];
  sort: TableSort;
  onToggleRow: (id: string) => void;
  onTogglePage: () => void;
  onSort: (key: SortKey, dir: SortDir | 'none') => void;
  onDelete: (item: FileItem) => void;
  onRetranslate: (item: FileItem) => void;
  onView: (item: FileItem) => void;
};

// Khung cuộn của DataTable (overflow: auto) bị vòng focus/hover của nút ở hàng cuối (::before/::after, bottom -3…-5px)
// đẩy cao hơn bảng 3px → 1–2 lần lăn chuột trên bảng cuộn khung này thay vì trang. Chỉ cho cuộn ngang; paddingBottom 6px chừa chỗ cho vòng focus để không bị cắt.
const TableFrame = styled.div({
  '& div:has(> table)': { overflowY: 'hidden', paddingBottom: 6 },
  // Hai luật dưới chỉ dành cho bố cục hàng ngang. Gamut chuyển sang xếp chồng (flex-direction: column) khi
  // container hẹp hơn breakpoint `sm` (768px, @container — cùng truy vấn với c_sm của ListCol/ListRow); ở đó flex-basis 0
  // sẽ làm xẹp CHIỀU CAO ô tên (mất tiêu đề "Tên").
  [`@container (min-width: ${breakpoints.sm})`]: {
    // Gamut 73.6.1: ô chọn-tất-cả ở thead dựng thiếu `type: "select"` (ô chọn từng hàng ở tbody thì có) nên dày hơn 8px
    // padding-right → mọi cột ở tiêu đề lệch 8px so với dữ liệu. Ép về cùng padding-right 0 để hai bên trùng toạ độ x.
    // Giả định lưới có `selectable` (có ô chọn, là <td> đầu hàng); không có ô chọn thì luật này không khớp phần tử nào.
    '& thead tr > td:first-of-type': { paddingRight: 0 },
    // Cột tên là cột `type: 'header'` duy nhất nên là <th> duy nhất của hàng (ô chọn là <td>) → `th:first-of-type` đúng là cột tên.
    // Mặc định nó `flex: 0 0 auto; overflow: visible` nên không co, không cắt: tên dài tràn sang cột sau. Cho nó nhận phần
    // chiều rộng còn lại, co được và cắt phần thừa.
    '& thead tr > th:first-of-type': { flex: '1 1 0', minWidth: 0 },
    // Chỉ ô thân mới cắt (overflow: hidden); ô tiêu đề ngắn nên không cắt để vòng focus của nút sắp xếp "Tên" không bị xén.
    '& tbody tr > th:first-of-type': { flex: '1 1 0', minWidth: 0, overflow: 'hidden' },
  },
});

// Anchor của Gamut là inline-block + white-space: normal nên tự xuống dòng ở dấu gạch ngang; ép nó thành block vừa khung
// và cắt CHỮ bên trong (NameText), không cắt chính anchor để vòng focus không bị xén. Tên đầy đủ hiện ở tooltip gốc;
// tên truy cập của link vẫn là tên đầy đủ. paddingRight chừa chỗ cho vòng focus ở mép phải ô tên.
const NameLine = styled.div({ paddingRight: 2, '& a': { display: 'block', maxWidth: '100%' } });
const NameText = styled.span({ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' });

// Mọi icon thao tác chiếm đúng một ô cố định (2rem, cỡ IconButton small) để các hàng thẳng cột.
const Slot = ({ children }: { children?: ReactNode }) => (
  <Box data-testid="action-slot" width="2rem" minWidth="2rem" height="2rem" flexShrink={0}>{children}</Box>
);

type IconProps = Pick<ComponentProps<typeof IconButton>, 'icon'> & {
  label: string;
  /** Có lý do = icon bị khoá: nhìn mờ, không kích hoạt được, tooltip hiện lý do. */
  disabledReason?: string;
  onClick?: () => void;
  href?: string;
};

// Nút <button disabled> không bắn sự kiện chuột nên tooltip không bao giờ hiện. Icon bị khoá dùng aria-disabled
// (Gamut tô mờ theo [aria-disabled='true']), không href, onClick bỏ trống và vẫn focus được bằng bàn phím.
function ActionIcon({ icon, label, disabledReason, onClick, href }: IconProps) {
  if (disabledReason) {
    return (
      <IconButton icon={icon} aria-label={label} tip={disabledReason} tipProps={FLOATING_TIP}
        aria-disabled="true" onClick={(event: MouseEvent) => event.preventDefault()} size="small" variant="secondary" />
    );
  }
  return <IconButton icon={icon} tip={label} tipProps={FLOATING_TIP} onClick={onClick} href={href}
    size="small" variant="secondary" />;
}

// Gamut gắn cứng aria-label tiếng Anh cho checkbox và nút sắp xếp ("Select All", "Select <id>", "sort by <khoá cột>" — tên
// truy cập không chứa chữ hiển thị, vi phạm WCAG 2.5.3). Chạy sau MỖI lần render: hàng mới dựng (đổi trang, polling) lại mang nhãn gốc.
const SORT_LABEL_OF_COLUMN: Record<SortColumn, string> = {
  filename: t('home.col.name'), created_at: t('home.col.created'), status: t('home.col.status'),
};
function relabel(root: HTMLElement, names: Map<string, string>) {
  root.querySelectorAll('[aria-label]').forEach((element) => {
    const label = element.getAttribute('aria-label') ?? '';
    let next: string | null = null;
    if (label === 'Select All') next = t('table.selectAll');
    else if (label.startsWith('Select ')) {
      const name = names.get(label.slice('Select '.length));
      if (name !== undefined) next = t('table.selectRow', { name });
    } else if (label.startsWith('sort by ')) {
      const column = label.slice('sort by '.length);
      if (isSortColumn(column)) next = t('table.sortBy', { column: SORT_LABEL_OF_COLUMN[column] });
    }
    if (next !== null && next !== label) element.setAttribute('aria-label', next);
  });
}

export function FileTable({
  items, loading, languageNames, meta, selected, sort, onToggleRow, onTogglePage, onSort, onDelete, onRetranslate, onView,
}: Props) {
  const frame = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (frame.current) relabel(frame.current, new Map(items.map((item) => [item.id, item.filename])));
  });
  const query: Query<FileItem> = sort ? { sort: { [COLUMN_OF_SORT[sort.key]]: sort.dir } } : {};
  const onQueryChange: OnQueryChange<FileItem> = (change) => {
    if (change.type === 'reset') onSort('created', 'none');
    else if (change.type === 'sort' && isSortColumn(change.payload.dimension)) {
      onSort(SORT_OF_COLUMN[change.payload.dimension], change.payload.value);
    }
  };
  return (
    <TableFrame ref={frame}>
      <DataGrid
        id="my-files"
        idKey="id"
        rows={items}
        loading={loading}
        selected={selected}
        query={query}
        onQueryChange={onQueryChange}
        onRowSelect={({ type, payload }) => {
          if (type === 'select-all') onTogglePage();
          else if (payload.rowId !== undefined) onToggleRow(payload.rowId);
        }}
        columns={[
          {
            key: 'filename', header: t('home.col.name'), size: 'xl', fill: true, type: 'header', sortable: true,
            render: (item) => (
              <FlexBox gap={12} alignItems="center" minWidth={0}>
                <Box flexShrink={0}><PdfIcon size={24} color="feedback-error" aria-hidden /></Box>
                <Box minWidth={0} flex={1}>
                  <NameLine title={item.filename}>
                    <RouterAnchor to={`/files/${item.id}`} variant="interface"><NameText>{item.filename}</NameText></RouterAnchor>
                  </NameLine>
                  <Text block fontSize={14} color="text-secondary" truncate="ellipsis" truncateLines={1}>
                    {fileCaption(item, languageNames[item.language] ?? item.language, meta)}
                  </Text>
                </Box>
              </FlexBox>
            ),
          },
          {
            key: 'created_at', header: t('home.col.created'), size: 'md', sortable: true,
            render: (item) => <Text as="span" fontSize={14}>{formatRelative(item.created_at)}</Text>,
          },
          {
            key: 'status', header: t('home.col.status'), size: 'md', sortable: true,
            render: (item) => <StatusBadge item={item} />,
          },
          {
            key: 'id', header: t('home.col.actions'), size: 'lg', justify: 'right',
            render: (item) => {
              const reason = hasTranslation(item) ? undefined : noTranslationReason(item);
              return (
                <FlexBox gap={4} justifyContent="flex-end">
                  <Slot>
                    <ActionIcon icon={ViewIcon} label={t('action.view')} disabledReason={reason} onClick={() => onView(item)} />
                  </Slot>
                  <Slot>
                    <ActionIcon icon={DownloadIcon} label={t('action.downloadTranslated')} disabledReason={reason}
                      href={filesApi.downloadUrl(item.id, 'translated')} />
                  </Slot>
                  <Slot>
                    <ActionIcon icon={FileDownloadIcon} label={t('action.downloadOriginal')}
                      href={filesApi.downloadUrl(item.id, 'original')} />
                  </Slot>
                  <Slot>
                    {/* Mọi dòng có ↻ ở cùng một ô; đang chờ / đang dịch (kể cả đang dựng lại / dịch lại) thì khoá kèm lý do. */}
                    <ActionIcon icon={RedoIcon} label={t('action.retranslate')} onClick={() => onRetranslate(item)}
                      disabledReason={isPending(item) ? t('action.retranslate.pending') : undefined} />
                  </Slot>
                  <Slot>
                    <IconButton icon={TrashIcon} tip={t('action.delete')} tipProps={FLOATING_TIP} onClick={() => onDelete(item)}
                      size="small" variant="secondary" disabled={item.status === 'running'} />
                  </Slot>
                </FlexBox>
              );
            },
          },
        ]}
      />
    </TableFrame>
  );
}
