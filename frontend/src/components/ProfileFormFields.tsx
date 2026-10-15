import { FlexBox, FormGroup, Input, Select, TextArea } from '@codecademy/gamut';
import type { StyleValues } from '../api/settings';
import { CUSTOM_MAX, ENUM_FIELDS, NAME_MAX, fieldLabel, valueOptions } from '../files/profiles';
import { t } from '../i18n/t';

type Props = {
  /** Tiền tố id: 'profile' (Dialog tab Hồ sơ dịch) | 'settings-profile' (form tại chỗ ở Cài đặt › Dịch thuật). */
  idPrefix: string;
  name: string;
  style: StyleValues;
  onNameChange: (name: string) => void;
  onStyleChange: (style: StyleValues) => void;
};

/** Tên + 8 ô chọn + "Yêu cầu riêng" của một hồ sơ (spec 2026-10-15 §9) — dùng chung cho Dialog ở tab Hồ sơ dịch và form tại chỗ ở
 *  Cài đặt › Dịch thuật. State do cha giữ; Select uncontrolled (defaultValue) — cha remount bằng `key` khi đổi hồ sơ đang sửa. */
export function ProfileFormFields({ idPrefix, name, style, onNameChange, onStyleChange }: Props) {
  return (
    <FlexBox flexDirection="column" gap={12}>
      <FormGroup label={t('profiles.form.name')} htmlFor={`${idPrefix}-name`} isSoloField>
        <Input id={`${idPrefix}-name`} value={name} maxLength={NAME_MAX} onChange={(event) => onNameChange(event.target.value)} />
      </FormGroup>
      {ENUM_FIELDS.map((field) => (
        <FormGroup key={field} label={fieldLabel(field)} htmlFor={`${idPrefix}-${field}`} isSoloField>
          <Select id={`${idPrefix}-${field}`} defaultValue={style[field]} options={valueOptions(field)}
            onChange={(event) => onStyleChange({ ...style, [field]: event.target.value })} />
        </FormGroup>
      ))}
      <FormGroup label={fieldLabel('custom_instructions')} htmlFor={`${idPrefix}-custom_instructions`} isSoloField
        description={t('profiles.form.counter', { n: style.custom_instructions.length, max: CUSTOM_MAX })}>
        <TextArea id={`${idPrefix}-custom_instructions`} rows={4} value={style.custom_instructions} maxLength={CUSTOM_MAX}
          onChange={(event) => onStyleChange({ ...style, custom_instructions: event.target.value })} />
      </FormGroup>
    </FlexBox>
  );
}
