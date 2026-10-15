import { useEffect, useRef, useState, type DragEvent } from 'react';
import styled from '@emotion/styled';
import {
  Alert, Box, FillButton, FlexBox, FormGroup, Modal, Select, StrokeButton, Text,
} from '@codecademy/gamut';
import { PdfIcon } from '@codecademy/gamut-icons';
import { css } from '@codecademy/gamut-styles';
import { toApiError } from '../api/client';
import { filesApi, type FileItem } from '../api/files';
import { settingsApi, type SettingsInfo } from '../api/settings';
import { chosenEngine, initialChoice, type EngineChoice } from '../files/engines';
import { fontOptions } from '../files/fonts';
import { pdfError } from '../files/validatePdf';
import { useMeta } from '../files/useMeta';
import { errorText, t } from '../i18n/t';
import { AdvancedFields, initialAdvanced, toAdvancedChoice, type AdvancedState } from './AdvancedFields';
import { EngineChoiceFields } from './EngineChoiceFields';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  onUploaded: (item: FileItem) => void;
  /** Tệp đã chọn sẵn khi hộp mở (vd. kéo thả ở đầu trang chủ). */
  initialFile?: File | null;
};

// Hộp Modal của Gamut cao tối đa (khung nhìn − 4rem) nhưng không tự cuộn: đủ trường + ô font thì nội dung tràn khỏi
// hộp và nút "Dịch" nằm dưới mép màn hình (720px, 768px, điện thoại). Chỉ vùng nội dung cuộn — tiêu đề và nút đóng
// (kèm tooltip của nó) đứng yên; cuộn cả hộp thì tooltip của nút đóng bị cắt. Vùng cuộn tràn sang padding 24px (1.5rem)
// của hộp hai bên (và 0.5rem phía dưới) để viền focus của trường / nút sát mép không bị cắt; chỗ trống bù bằng padding.
// `modal-content` là test id Gamut gắn cho vùng nội dung (`scrollable` của Gamut chỉ cuộn, không cho bù mép này).
const ScrollingModal = styled(Modal)({
  '& [data-testid="modal-content"]': {
    overflowY: 'auto',
    minHeight: 0,
    margin: '0 -1.5rem -0.5rem',
    padding: '0 1.5rem',
  },
});

// Hàng nút dính đáy vùng cuộn, nền phủ hết bề ngang (nội dung cuộn chui dưới nó). pt 16 = khoảng cách cũ giữa các
// trường; pb 8 chứa viền focus của nút và cùng 1rem padding còn lại của hộp đúng bằng 24px cũ dưới hàng nút.
const ActionRow = styled.div(
  css({
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 8,
    position: 'sticky',
    bottom: 0,
    bg: 'background',
    pt: 16,
    px: 24,
    pb: 8,
  }),
  { margin: '0 -1.5rem' }, // ngoài thang spacing của Gamut (không có giá trị âm)
);

export function UploadModal({ isOpen, onClose, onUploaded, initialFile }: Props) {
  const meta = useMeta();
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  // Chưa biết cài đặt thì chưa cho gửi: gửi sớm = server tự lấy mặc định (có thể là AI trả phí).
  const [settingsState, setSettingsState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [choice, setChoice] = useState<EngineChoice | null>(null);
  // null khi chưa có / không tải được cài đặt → không gửi `font` (server dùng mặc định, vô hại vì không trả phí).
  const [font, setFont] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState<AdvancedState | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const chosenLanguage = language ?? meta?.default_language ?? 'vi';

  useEffect(() => {
    if (!isOpen) {
      setFile(null);
      setLanguage(null);
      setError(null);
      setBusy(false);
      setSettings(null);
      setSettingsState('loading');
      setChoice(null);
      setFont(null);
      setAdvanced(null);
      return;
    }
    // Không cache: người dùng có thể vừa thêm/xoá key ở Cài đặt. Lỗi → ẩn nhóm chế độ và gửi RÕ engine
    // google_free (không bao giờ để server âm thầm dùng mặc định — có thể là AI trả phí).
    let alive = true;
    settingsApi
      .get()
      .then((loaded) => {
        if (!alive) return;
        setSettings(loaded);
        setChoice(initialChoice(loaded));
        setFont(loaded.default_font);
        setAdvanced(loaded.advance_mode ? initialAdvanced(loaded) : null); // tải lên: chọn sẵn hồ sơ mặc định
        setSettingsState('ready');
      })
      .catch(() => { if (alive) setSettingsState('failed'); });
    return () => { alive = false; };
  }, [isOpen]);

  function pick(candidate: File | undefined) {
    if (!candidate) return;
    const problem = pdfError(candidate, meta);
    setFile(problem ? null : candidate);
    setError(problem);
  }

  // Mở hộp với tệp đã chọn sẵn — đúng một lần mỗi lần mở: meta tới muộn / render lại không được ghi đè tệp người dùng chọn lại.
  const appliedInitial = useRef<File | null>(null);
  useEffect(() => {
    if (!isOpen) appliedInitial.current = null;
    else if (initialFile && appliedInitial.current !== initialFile) {
      appliedInitial.current = initialFile;
      pick(initialFile);
    }
  }, [isOpen, initialFile]);

  async function submit() {
    if (!file) {
      setError(t('upload.needFile'));
      return;
    }
    setBusy(true);
    setError(null);
    const picked = choice ? chosenEngine(choice) : { engine: 'google_free', model: null };
    try {
      // Thành công thì giữ busy: trang cha chuyển sang màn tệp, nút không được bấm lại.
      // Trường nâng cao chỉ đi cùng động cơ AI (server từ chối trường hợp khác): đổi sang Dịch thuần là bỏ hết.
      const extra = settings && advanced && picked.engine === 'gemini' ? toAdvancedChoice(advanced, settings) : null;
      onUploaded(await filesApi.upload(file, chosenLanguage, picked.engine, picked.model, font ?? undefined, extra));
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(errorText(apiError.code, apiError.params));
      setBusy(false);
    }
  }

  const languageOptions = Object.fromEntries((meta?.languages ?? []).map((item) => [item.code, item.name]));
  return (
    <ScrollingModal isOpen={isOpen} onRequestClose={onClose} title={t('upload.title')} size="medium">
      <FlexBox flexDirection="column" gap={16}>
        <Box
          data-testid="dropzone"
          border={1}
          borderStyle="dashed"
          borderColor={dragging ? 'primary' : 'border-secondary'}
          borderRadius="md"
          p={24}
          textAlign="center"
          onDragOver={(event: DragEvent) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event: DragEvent) => {
            event.preventDefault();
            setDragging(false);
            pick(event.dataTransfer.files[0]);
          }}
        >
          <PdfIcon size={32} color="feedback-error" aria-hidden />
          <Text mt={8}>{t('upload.drop')}</Text>
          <Text color="text-secondary" fontSize={14} my={8}>{t('upload.or')}</Text>
          <StrokeButton type="button" size="small" onClick={() => inputRef.current?.click()}>
            {t('upload.choose')}
          </StrokeButton>
          <input
            ref={inputRef}
            data-testid="file-input"
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(event) => {
              pick(event.target.files?.[0]);
              event.target.value = '';
            }}
          />
          {meta && <Text color="text-secondary" fontSize={14} mt={8}>{t('upload.limit', { mb: meta.max_upload_mb })}</Text>}
          {file && <Text mt={8} fontWeight="title">{t('upload.selected', { name: file.name })}</Text>}
        </Box>
        {/* isSoloField: bỏ hậu tố "(optional)" Gamut tự thêm vào label — field này luôn bắt buộc. */}
        <FormGroup label={t('upload.language')} htmlFor="upload-language" isSoloField>
          {/* Gamut's Select always sets defaultValue on the native <select> while also spreading
              a `value` prop through, so a controlled `value` warns ("must be either controlled or
              uncontrolled"). Use it uncontrolled instead: `key` forces a remount (picking up the
              right defaultValue) once `meta` arrives, and `language` state (set by onChange) stays
              the source of truth for the upload call below. */}
          <Select
            key={meta?.default_language ?? 'loading'}
            id="upload-language"
            defaultValue={chosenLanguage}
            options={languageOptions}
            onChange={(event) => setLanguage(event.target.value)}
          />
        </FormGroup>
        {settings && choice && <EngineChoiceFields idPrefix="upload" settings={settings} choice={choice} onChange={setChoice} />}
        {settings && (
          <FormGroup label={t('font.field')} htmlFor="upload-font" isSoloField>
            <Select key={settings.default_font} id="upload-font" defaultValue={settings.default_font}
              options={fontOptions()} onChange={(event) => setFont(event.target.value)} />
          </FormGroup>
        )}
        {/* Mục Nâng cao chỉ với động cơ AI (spec 2026-10-15 §6): dịch thuần không có hồ sơ/ngữ cảnh — không hiện gì, không câu nhắc. */}
        {settings && advanced && choice && choice.mode === 'ai' && (
          <AdvancedFields idPrefix="upload" settings={settings} value={advanced} onChange={setAdvanced}
            onProfilesChange={(profiles) => setSettings((current) => (current ? { ...current, profiles } : current))} />
        )}
        {error && <Alert type="error" placement="inline">{error}</Alert>}
      </FlexBox>
      <ActionRow data-testid="upload-actions">
        <StrokeButton type="button" onClick={onClose}>{t('common.cancel')}</StrokeButton>
        <FillButton type="button" onClick={submit} disabled={busy || settingsState === 'loading'}>
          {busy ? t('upload.submitting') : t('upload.submit')}
        </FillButton>
      </ActionRow>
    </ScrollingModal>
  );
}
