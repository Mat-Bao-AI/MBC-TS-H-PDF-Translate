import { useRef, useState, type DragEvent } from 'react';
import { Alert, Anchor, Box, FlexBox, Text } from '@codecademy/gamut';
import { UploadIcon } from '@codecademy/gamut-icons';
import type { Meta } from '../api/files';
import { pdfError } from '../files/validatePdf';
import { t } from '../i18n/t';

type Props = { meta: Meta | null; onFile: (file: File) => void };

/** Vùng kéo thả PDF ở đầu trang chủ. Tệp hợp lệ được trao cho trang cha (mở hộp tải lên với tệp đã chọn);
 * tệp sai chỉ hiện lỗi ngay dưới vùng. Bàn phím dùng nút "chọn từ máy tính". */
export function HeroDropZone({ meta, onFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function take(candidate: File | undefined) {
    if (!candidate) return;
    const problem = pdfError(candidate, meta);
    setError(problem);
    if (!problem) onFile(candidate);
  }

  // Nút và vùng cùng mở hộp chọn tệp: click vào nút nổi bọt lên vùng nên chỉ vùng xử lý (một lần).
  // Ô input nằm NGOÀI vùng — input.click() cũng nổi bọt, đặt trong vùng sẽ gọi lại chính nó.
  const [before, after] = t('home.drop').split('{link}'); // vị trí liên kết nằm trong chuỗi i18n, không ghép tay
  const open = () => inputRef.current?.click();

  return (
    <Box>
      <FlexBox
        data-testid="hero-dropzone"
        data-dragging={dragging}
        alignItems="center"
        justifyContent="center"
        gap={12}
        flexWrap="wrap"
        border={1}
        borderStyle="dashed"
        borderColor={dragging ? 'primary' : 'border-secondary'}
        borderRadius="md"
        bg={dragging ? 'background-selected' : 'background'}
        p={32}
        textAlign="center"
        onClick={open}
        onDragOver={(event: DragEvent) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={(event: DragEvent) => {
          // Rời sang phần tử con (icon, chữ, nút) cũng bắn dragleave ở vùng — bỏ qua kẻo viền nhấp nháy.
          if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
          setDragging(false);
        }}
        onDrop={(event: DragEvent) => {
          event.preventDefault();
          setDragging(false);
          take(event.dataTransfer.files[0]);
        }}
      >
        <UploadIcon size={32} aria-hidden />
        <Text as="p">
          {before}
          <Anchor variant="inline">{t('home.drop.link')}</Anchor>
          {after}
        </Text>
      </FlexBox>
      <input
        ref={inputRef}
        data-testid="hero-file-input"
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(event) => {
          take(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
      {error && (
        <Box mt={12} role="alert">
          <Alert type="error" placement="inline">{error}</Alert>
        </Box>
      )}
    </Box>
  );
}
