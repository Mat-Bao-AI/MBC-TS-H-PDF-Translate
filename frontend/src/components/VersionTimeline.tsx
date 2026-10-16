import styled from '@emotion/styled';
import { css } from '@codecademy/gamut-styles';
import { StrokeButton } from '@codecademy/gamut';
import { entryTime, type VersionEntry } from '../files/versions';
import { t } from '../i18n/t';

const THUMB = 18; // px: bề rộng tay cầm, dùng để căn mốc/chú thích đúng tâm tay cầm

/** Vị trí 0..1 của một chỉ số trên thanh. Một bản duy nhất → 0. */
const fraction = (index: number, count: number) => (count > 1 ? index / (count - 1) : 0);
const centreOf = (pos: number) => `calc(${THUMB / 2}px + (100% - ${THUMB}px) * ${pos})`;

/** Nhãn một bản: "Bản 2 · hôm nay lúc 09:12" (+ "(lúc bị thay)" khi chỉ biết giờ bị thay — bản cất trước 1b). */
export function versionLabel(entry: VersionEntry): string {
  const time = entryTime(entry);
  const name = t('detail.version.label', { n: entry.version_no });
  return time ? `${name} · ${time}` : name;
}

/** Đọc cho trình đọc màn hình: nhãn + "hiện tại" + "tệp không còn" (trạng thái mờ không được chỉ nằm ở màu). */
function valueText(entry: VersionEntry): string {
  return [versionLabel(entry), entry.id === null ? t('detail.version.current') : null, entry.available ? null : t('detail.version.missing')]
    .filter(Boolean).join(' · ');
}

// Gamut không có Slider: <input type="range"> gốc, vẽ lại bằng styled. Hai ô range chồng trên cùng một thanh (kỹ thuật dual-range):
// ô không bắt chuột (pointer-events none), chỉ tay cầm bắt (auto) nên kéo được từng tay cầm. Lưới: chú thích / ◀ thanh ▶ / mốc.
const Layout = styled.div({ display: 'grid', gridTemplateColumns: 'auto minmax(160px, 1fr) auto', columnGap: 12, alignItems: 'center' });
// Mỗi ô một vùng lưới tường minh: không để lưới tự xếp (ô chỉ có phần tử absolute sẽ co về 0 rộng).
// Khoảng cách giữa mũi tên (aria-hidden) và chữ nút: lề trên span, không chèn khoảng trắng vào tên truy cập.
const GlyphBefore = styled.span({ marginRight: 6 });
const GlyphAfter = styled.span({ marginLeft: 6 });
const Cell = styled.div<{ row: number; col: number }>(({ row, col }) => ({ gridRow: row, gridColumn: col, minWidth: 0 }));
const Track = styled.div({ position: 'relative', height: 28, width: '100%' });
const Rail = styled.div(css({ position: 'absolute', left: 9, right: 9, top: 12, height: 4, borderRadius: 'full', bg: 'text-disabled' }));
const thumb = { appearance: 'none', width: THUMB, height: THUMB, borderRadius: 'full', borderWidth: '2px', borderStyle: 'solid', borderColor: 'primary', bg: 'background', cursor: 'pointer', pointerEvents: 'auto' } as const;
const Range = styled.input(
  css({
    appearance: 'none',
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    m: 0,
    p: 0,
    bg: 'transparent',
    color: 'primary',
    pointerEvents: 'none',
    '&::-webkit-slider-runnable-track': { background: 'transparent', height: 28 },
    '&::-moz-range-track': { background: 'transparent' },
    '&::-webkit-slider-thumb': { ...thumb, marginTop: `${(28 - THUMB) / 2}px` }, // WebKit đặt tay cầm sát đỉnh rãnh: hạ xuống giữa rãnh
    '&::-moz-range-thumb': thumb,
    '&:focus-visible': { outline: 'none' },
    '&:focus-visible::-webkit-slider-thumb': { outline: '2px solid', outlineColor: 'primary', outlineOffset: '2px' },
    '&:focus-visible::-moz-range-thumb': { outline: '2px solid', outlineColor: 'primary', outlineOffset: '2px' },
  }),
);
const ROW = 22;
const Captions = styled.div<{ rows: number }>(({ rows }) => ({ position: 'relative', height: rows * ROW }));
const Caption = styled.div<{ pos: number; row: number }>(({ pos, row }) => ({
  position: 'absolute', top: row * ROW, left: centreOf(pos), whiteSpace: 'nowrap', transform: `translateX(-${pos * 100}%)`, fontSize: 13,
}));
const Ticks = styled.ol({ position: 'relative', height: 46, margin: 0, padding: 0, listStyle: 'none' });
const MissingMark = styled.span({ fontSize: 11 });
const Tick = styled.li<{ pos: number }>(({ pos }) => ({
  position: 'absolute', top: 0, left: centreOf(pos), transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center',
  fontSize: 12, whiteSpace: 'nowrap',
  '&::before': { content: '""', width: 1, height: 6, background: 'currentColor' },
  '&[data-muted="true"]': { opacity: 0.55 },
}));

type Props = {
  entries: VersionEntry[]; // tăng dần theo version_no
  rightIndex: number;
  leftIndex: number | null; // null = không có bản trước
  anyPair: boolean;
  narrow: boolean; // màn hẹp: chỉ ghi nhãn mốc đầu, cuối và mốc đang chọn
  onRightChange: (index: number) => void;
  onLeftChange: (index: number) => void;
};

/** Thanh trượt các bản kiểu "Revisions" của WordPress: một tay cầm (bản bên phải) hoặc hai (so sánh hai bản bất kỳ), mốc có nhãn
 *  bên dưới, chú thích "Bản N · giờ" trên tay cầm, ◀ Trước / Sau ▶ hai đầu. Trạng thái do trang giữ; ở đây chỉ vẽ và báo chỉ số mới. */
export function VersionTimeline({ entries, rightIndex, leftIndex, anyPair, narrow, onRightChange, onLeftChange }: Props) {
  const count = entries.length;
  const last = count - 1;
  const showLeft = anyPair && leftIndex !== null;
  const minRight = showLeft ? 1 : 0; // so sánh hai bản: phải ≥ Bản thứ hai (trái luôn bị đẩy xuống theo phải)
  const range = (index: number, name: string, onChange: (index: number) => void) => (
    <Range type="range" min={0} max={last} step={1} value={index} aria-label={name} aria-valuetext={valueText(entries[index])}
      onChange={(event) => onChange(Number(event.target.value))} />
  );

  return (
    <Layout data-testid="timeline">
      <Cell row={1} col={2}>
        <Captions rows={showLeft ? 2 : 1}>
          {showLeft && <Caption pos={fraction(leftIndex, count)} row={0} data-testid="caption-left">{versionLabel(entries[leftIndex])}</Caption>}
          <Caption pos={fraction(rightIndex, count)} row={showLeft ? 1 : 0} data-testid="caption-right">{versionLabel(entries[rightIndex])}</Caption>
        </Captions>
      </Cell>
      <Cell row={2} col={1}>
        <StrokeButton type="button" size="small" onClick={() => onRightChange(rightIndex - 1)} disabled={rightIndex <= minRight}>
          <GlyphBefore aria-hidden="true">◀</GlyphBefore>{t('versions.prev')}
        </StrokeButton>
      </Cell>
      <Cell row={2} col={2} data-testid="track-cell">
        <Track>
          <Rail />
          {showLeft && range(leftIndex, t('versions.sliderLeft'), onLeftChange)}
          {range(rightIndex, t('versions.sliderRight'), onRightChange)}
        </Track>
      </Cell>
      <Cell row={2} col={3}>
        <StrokeButton type="button" size="small" onClick={() => onRightChange(rightIndex + 1)} disabled={rightIndex === last}>
          {t('versions.next')}<GlyphAfter aria-hidden="true">▶</GlyphAfter>
        </StrokeButton>
      </Cell>
      <Cell row={3} col={2}>
        <Ticks data-testid="ticks">
          {entries.map((entry, index) => {
            const labelled = !narrow || index === 0 || index === last || index === rightIndex || (showLeft && index === leftIndex);
            return (
              <Tick key={entry.id ?? 'current'} pos={fraction(index, count)} data-testid={`tick-${entry.version_no}`} data-muted={entry.available ? undefined : 'true'}>
                {labelled && <span>{t('detail.version.label', { n: entry.version_no })}</span>}
                {/* Dấu ngắn thay cho dòng "tệp không còn" (chồng chữ khi mốc sát nhau); nội dung đầy đủ nằm ở tên truy cập/title. */}
                {!entry.available && <MissingMark role="img" aria-label={t('detail.version.missing')} title={t('detail.version.missing')}>✕</MissingMark>}
              </Tick>
            );
          })}
        </Ticks>
      </Cell>
    </Layout>
  );
}
