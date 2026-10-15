import { useEffect, useState, type ComponentProps } from 'react';
import styled from '@emotion/styled';
import { Alert, Dialog, FlexBox, FormGroup, Radio, RadioGroup, Select, Spinner, Text } from '@codecademy/gamut';
import type { FileItem, RetranslateRequest } from '../api/files';
import { settingsApi, type SettingsInfo } from '../api/settings';
import { choiceFor, chosenEngine, initialChoice, type EngineChoice } from '../files/engines';
import { fontOptions } from '../files/fonts';
import { useMeta } from '../files/useMeta';
import { t } from '../i18n/t';
import { AdvancedFields, initialAdvanced, toAdvancedChoice, type AdvancedState } from './AdvancedFields';
import { EngineChoiceFields } from './EngineChoiceFields';

/** Một tệp (chọn sẵn theo chính tệp đó) hoặc nhiều tệp đã chọn (`count`, kể cả "Chọn tất cả N tệp"). */
export type RetranslateTarget = { item: FileItem } | { count: number };
type Scope = 'keep' | 'apply';
type ConfirmCta = ComponentProps<typeof Dialog>['confirmCta'];

type Props = {
  /** null = hộp đóng. */
  target: RetranslateTarget | null;
  onClose: () => void;
  /**
   * Gamut gọi onRequestClose (→ onClose) TRƯỚC hàm này: hộp đã đóng, trang cha gửi request và báo kết quả trên trang
   * (như "Dựng lại"). null = hàng loạt, "Giữ cài đặt riêng của từng tệp". Đơn: kèm `profile/style/context` khi động cơ là AI
   * và Chế độ nâng cao bật (khoá không có nội dung thì bỏ hẳn, không gửi null).
   */
  onConfirm: (settings: RetranslateRequest | null) => void;
};

// Dialog của Gamut cao tối đa (khung nhìn − 4rem) nhưng không tự cuộn: dải cảnh báo + bốn trường thì nút "Dịch lại" rơi
// khỏi màn hình thấp. Chỉ vùng trường cuộn; tràn 0.5rem sang hai bên để viền focus của trường sát mép không bị cắt.
const FieldsScroll = styled.div({ maxHeight: 'calc(100vh - 14rem)', overflowY: 'auto', margin: '0 -0.5rem', padding: '0 0.5rem 0.25rem' });

/** Hộp "Dịch lại" (spec 2026-10-05 §6): đơn — chọn sẵn theo tệp; hàng loạt — giữ cài đặt riêng (mặc định) hoặc áp một cài đặt. */
export function RetranslateDialog({ target, onClose, onConfirm }: Props) {
  const meta = useMeta();
  const open = target !== null;
  const item = target !== null && 'item' in target ? target.item : null;
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [settingsState, setSettingsState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [scope, setScope] = useState<Scope>('keep');
  // null = người dùng chưa đổi: dùng giá trị chọn sẵn (theo tệp, hoặc theo mặc định khi áp một cài đặt cho nhiều tệp).
  const [language, setLanguage] = useState<string | null>(null);
  const [choice, setChoice] = useState<EngineChoice | null>(null);
  const [font, setFont] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState<AdvancedState | null>(null);

  useEffect(() => {
    if (!open) {
      setSettings(null);
      setSettingsState('loading');
      setScope('keep');
      setLanguage(null);
      setChoice(null);
      setFont(null);
      setAdvanced(null);
      return;
    }
    // Không cache (như hộp tải lên): người dùng có thể vừa thêm/xoá key ở Cài đặt.
    let alive = true;
    settingsApi
      .get()
      .then((loaded) => {
        if (!alive) return;
        setSettings(loaded);
        // null (tệp cơ bản) ≠ bỏ trống (tải lên): dịch lại đơn không bao giờ chọn sẵn hồ sơ mặc định (spec §8).
        setAdvanced(loaded.advance_mode && item ? initialAdvanced(loaded, item.config ?? null) : null);
        setSettingsState('ready');
      })
      .catch(() => { if (alive) setSettingsState('failed'); });
    return () => { alive = false; };
  }, [open, item?.id]);

  const prefix = item ? 'retranslate' : 'bulk-retranslate';
  const withFields = item !== null || scope === 'apply';
  const defaultLanguage = item ? item.language : meta?.default_language ?? 'vi';
  const defaultFont = item ? item.font : settings?.default_font ?? 'auto';
  const chosenLanguage = language ?? defaultLanguage;
  const chosenFont = font ?? defaultFont;
  const chosenChoice = choice ?? (settings ? (item ? choiceFor(settings, item.engine, item.model) : initialChoice(settings)) : null);
  // Chưa biết cài đặt thì chưa có engine/model để gửi: khoá nút (không bao giờ để server tự chọn — có thể là AI trả phí).
  const ready = !withFields || chosenChoice !== null;

  function confirm() {
    if (!withFields) {
      onConfirm(null);
      return;
    }
    if (!chosenChoice) return;
    const four = { language: chosenLanguage, ...chosenEngine(chosenChoice), font: chosenFont };
    const extra = item && settings && advanced && four.engine === 'gemini' ? toAdvancedChoice(advanced, settings) : null;
    // Server coi mọi khoá nâng cao có mặt là "đã yêu cầu": chỉ thêm khoá có nội dung thật.
    onConfirm({
      ...four,
      ...(extra?.profile ? { profile: extra.profile } : {}),
      ...(extra?.style ? { style: extra.style } : {}),
      ...(extra?.context ? { context: extra.context } : {}),
    });
  }

  let title = '';
  if (target) title = 'item' in target ? t('retranslate.title', { name: target.item.filename }) : t('retranslate.bulkTitle', { n: target.count });
  const warning = !item
    ? `${t('retranslate.warnDone')} ${t('retranslate.warnQueue')}`
    : item.status === 'error' ? t('retranslate.warnError') : t('retranslate.warnDone');
  const languageOptions = Object.fromEntries((meta?.languages ?? []).map((entry) => [entry.code, entry.name]));
  // Kiểu `confirmCta` của Gamut không khai `disabled`, nhưng Dialog trải cả object lên FillButton — test
  // "keeps Dịch lại locked until the settings are known…" canh việc này khi nâng Gamut.
  const confirmCta = { children: t('retranslate.confirm'), onClick: confirm, disabled: !ready } as ConfirmCta;

  return (
    <Dialog isOpen={open} title={title} size="medium" onRequestClose={onClose} confirmCta={confirmCta}
      cancelCta={{ children: t('common.cancel'), onClick: onClose }}>
      <FieldsScroll data-testid="retranslate-fields">
        <FlexBox flexDirection="column" gap={16}>
          <Alert type="notice" placement="inline">{warning}</Alert>
          {!item && settings?.advance_mode && <Text fontSize={14} color="text-secondary">{t('retranslate.bulkKeepsConfig')}</Text>}
          {!item && (
            // Như hộp tải lên: `checked` trên từng Radio, htmlForPrefix cho id, không truyền `id` cho Radio.
            <RadioGroup name="bulk-retranslate-scope" htmlForPrefix="bulk-retranslate-scope" aria-label={t('retranslate.scope')}
              onChange={(event) => setScope(event.target.value as Scope)}>
              <Radio label={t('retranslate.scope.keep')} value="keep" checked={scope === 'keep'} />
              <Radio label={t('retranslate.scope.apply')} value="apply" checked={scope === 'apply'} />
            </RadioGroup>
          )}
          {withFields && (
            <>
              <FormGroup label={t('upload.language')} htmlFor={`${prefix}-language`} isSoloField>
                {/* Select của Gamut là uncontrolled: key đổi khi danh sách ngôn ngữ tới để nhận lại defaultValue. */}
                <Select key={`${prefix}-language-${meta ? defaultLanguage : 'loading'}`} id={`${prefix}-language`}
                  defaultValue={chosenLanguage} options={languageOptions} onChange={(event) => setLanguage(event.target.value)} />
              </FormGroup>
              {settingsState === 'loading' && <Spinner size={24} />}
              {settingsState === 'failed' && <Alert type="error" placement="inline">{t('settings.loadError')}</Alert>}
              {settings && chosenChoice && (
                <EngineChoiceFields idPrefix={prefix} settings={settings} choice={chosenChoice} onChange={setChoice} />
              )}
              {settings && (
                <FormGroup label={t('font.field')} htmlFor={`${prefix}-font`} isSoloField>
                  <Select key={`${prefix}-font-${defaultFont}`} id={`${prefix}-font`} defaultValue={chosenFont}
                    options={fontOptions()} onChange={(event) => setFont(event.target.value)} />
                </FormGroup>
              )}
              {item && settings && advanced && chosenChoice && chosenChoice.mode === 'ai' && (
                <AdvancedFields idPrefix="retranslate" settings={settings} value={advanced} onChange={setAdvanced}
                  onProfilesChange={(profiles) => setSettings((current) => (current ? { ...current, profiles } : current))} />
              )}
            </>
          )}
        </FlexBox>
      </FieldsScroll>
    </Dialog>
  );
}
