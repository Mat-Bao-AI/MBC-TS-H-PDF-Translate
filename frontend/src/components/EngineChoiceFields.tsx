import { Box, FormGroup, Radio, RadioGroup, Select, Text } from '@codecademy/gamut';
import type { EngineMode, SettingsInfo } from '../api/settings';
import { isAvailable, modelOptions, switchMode, type EngineChoice } from '../files/engines';
import { t } from '../i18n/t';
import { RouterAnchor } from './RouterAnchor';

type Props = {
  /** Tiền tố id/name. 'upload' giữ nguyên id cũ của hộp tải lên: upload-mode, upload-engine, upload-model. */
  idPrefix: string;
  settings: SettingsInfo;
  choice: EngineChoice;
  onChange: (next: EngineChoice) => void;
};

/** "Chế độ dịch" (Dịch thuần / Dịch bằng AI) + "Dịch bằng" hoặc "Model" — hộp tải lên và hộp dịch lại dùng chung. */
export function EngineChoiceFields({ idPrefix, settings, choice, onChange }: Props) {
  const geminiAvailable = isAvailable(settings, 'gemini');
  const plainEngines = settings.engines.filter((engine) => engine.mode === 'plain');
  const needsKeyHint = !geminiAvailable || plainEngines.some((engine) => engine.available === false);
  return (
    <Box>
      <Text as="p" fontWeight="title" mb={8}>{t('upload.mode')}</Text>
      {/* RadioGroup của Gamut không xử lý `selected`: `checked` đặt trên từng Radio; htmlForPrefix
          tạo id input = for của label — KHÔNG truyền `id` cho Radio (label sẽ mất liên kết). */}
      <RadioGroup name={`${idPrefix}-mode`} htmlForPrefix={`${idPrefix}-mode`} aria-label={t('upload.mode')}
        onChange={(event) => onChange(switchMode(settings, choice, event.target.value as EngineMode))}>
        <Radio label={t('mode.plain')} value="plain" checked={choice.mode === 'plain'} />
        <Radio label={t('mode.ai')} value="ai" checked={choice.mode === 'ai'} disabled={!geminiAvailable} />
      </RadioGroup>
      {choice.mode === 'plain' ? (
        <Box mt={12}>
          <Text as="p" fontSize={14} mb={4}>{t('upload.engine')}</Text>
          <RadioGroup name={`${idPrefix}-engine`} htmlForPrefix={`${idPrefix}-engine`} aria-label={t('upload.engine')}
            onChange={(event) => onChange({ ...choice, engine: event.target.value })}>
            {plainEngines.map((engine) => (
              <Radio key={engine.id} label={engine.label} value={engine.id} checked={choice.engine === engine.id}
                disabled={engine.available === false} />
            ))}
          </RadioGroup>
        </Box>
      ) : (
        <Box mt={12}>
          <FormGroup label={t('upload.model')} htmlFor={`${idPrefix}-model`} isSoloField>
            <Select
              key={`${settings.gemini_models.map((model) => model.id).join(',')}|${settings.default_model ?? ''}`}
              id={`${idPrefix}-model`}
              defaultValue={choice.model}
              options={modelOptions(settings.gemini_models)}
              onChange={(event) => onChange({ ...choice, model: event.target.value })}
            />
          </FormGroup>
        </Box>
      )}
      {needsKeyHint && (
        <Text fontSize={14} color="text-secondary" mt={8}>
          {t('upload.noKey')} <RouterAnchor to="/settings/translation">{t('upload.addKey')}</RouterAnchor>
        </Text>
      )}
    </Box>
  );
}
