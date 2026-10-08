import type { ChangeEvent } from 'react';
import { FlexBox, FormGroup, Input, Select } from '@codecademy/gamut';
import type { PasswordStatus, SmtpBody, SmtpInfo, SmtpSecurity } from '../api/system';
import { t, type MessageKey } from '../i18n/t';

/** Sáu ô SMTP — dùng chung cho wizard bước 2 và thẻ "Gửi thư (SMTP)". `port` giữ dạng chuỗi (ô số), đổi sang số lúc gửi. */
export type SmtpForm = { host: string; port: string; security: SmtpSecurity; username: string; password: string; from: string };

type Props = {
  idPrefix: string;
  value: SmtpForm;
  onChange: (next: SmtpForm) => void;
  /** Ô đang sai theo `field` của 422 invalid_smtp; null = không có. */
  errorField: string | null;
  passwordStatus: PasswordStatus;
  /** Máy chủ / kiểu bảo mật đã khác giá trị đang lưu: mật khẩu trống không còn được giữ lại → bỏ gợi ý "đã lưu", đòi nhập lại. */
  passwordRequired?: boolean;
  /** Tăng mỗi lần form được nạp lại từ server: dựng lại Select (uncontrolled) mà KHÔNG mất focus khi người dùng đổi giá trị. */
  resetKey?: number;
};

const SECURITY_LABELS: Record<SmtpSecurity, MessageKey> = {
  starttls: 'system.smtp.security.starttls', ssl: 'system.smtp.security.ssl', none: 'system.smtp.security.none',
};
const PASSWORD_HINT: Partial<Record<PasswordStatus, MessageKey>> = {
  saved: 'system.smtp.password.saved', unreadable: 'system.smtp.password.unreadable',
};

export const emptySmtp = (): SmtpForm => ({ host: '', port: '587', security: 'starttls', username: '', password: '', from: '' });

export const smtpFromInfo = (info: SmtpInfo): SmtpForm => ({
  host: info.host ?? '', port: String(info.port || 587), security: info.security || 'starttls',
  username: info.username ?? '', password: '', from: info.from ?? '',
});

/** Thân PUT / thử: mật khẩu trống thì KHÔNG gửi khoá `password` (server giữ mật khẩu đã lưu). */
export function smtpBody(form: SmtpForm): SmtpBody {
  return {
    host: form.host.trim(), port: Number(form.port), security: form.security, username: form.username.trim(),
    from: form.from.trim(), ...(form.password ? { password: form.password } : {}),
  };
}

export function SmtpFields({ idPrefix, value, onChange, errorField, passwordStatus, passwordRequired = false, resetKey = 0 }: Props) {
  const set = (key: keyof SmtpForm) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...value, [key]: event.target.value });
  const error = (field: string) => (errorField === field ? t('system.smtp.invalidField') : undefined);
  const id = (field: string) => `${idPrefix}-${field}`;
  const passwordHint: MessageKey | undefined =
    passwordRequired && passwordStatus === 'saved'
      ? (value.password === '' ? 'system.smtp.password.needed' : undefined)
      : PASSWORD_HINT[passwordStatus];
  return (
    <FlexBox flexDirection="column" gap={16}>
      <FormGroup label={t('system.smtp.host')} htmlFor={id('host')} error={error('host')} isSoloField>
        <Input id={id('host')} value={value.host} autoComplete="off" error={Boolean(error('host'))} onChange={set('host')} />
      </FormGroup>
      <FlexBox gap={16} flexWrap="wrap">
        <FormGroup label={t('system.smtp.port')} htmlFor={id('port')} error={error('port')} isSoloField>
          <Input id={id('port')} type="number" min={1} max={65535} value={value.port} error={Boolean(error('port'))} onChange={set('port')} />
        </FormGroup>
        <FormGroup label={t('system.smtp.security')} htmlFor={id('security')} error={error('security')} isSoloField>
          {/* Select của Gamut là uncontrolled: key theo `resetKey` (lần nạp lại từ server), KHÔNG theo giá trị đang chọn, để không mất focus. */}
          <Select key={`${id('security')}-${resetKey}`} id={id('security')} defaultValue={value.security}
            options={Object.fromEntries((Object.keys(SECURITY_LABELS) as SmtpSecurity[]).map((k) => [k, t(SECURITY_LABELS[k])]))}
            onChange={set('security')} />
        </FormGroup>
      </FlexBox>
      <FormGroup label={t('system.smtp.username')} htmlFor={id('username')} error={error('username')} isSoloField>
        <Input id={id('username')} value={value.username} autoComplete="off" error={Boolean(error('username'))} onChange={set('username')} />
      </FormGroup>
      <FormGroup label={t('system.smtp.password')} htmlFor={id('password')} error={error('password')}
        description={passwordHint ? t(passwordHint) : undefined} isSoloField>
        <Input id={id('password')} type="password" autoComplete="new-password" data-1p-ignore data-lpignore="true" value={value.password}
          error={Boolean(error('password'))} onChange={set('password')} />
      </FormGroup>
      <FormGroup label={t('system.smtp.from')} htmlFor={id('from')} error={error('from')} isSoloField>
        <Input id={id('from')} value={value.from} autoComplete="off" error={Boolean(error('from'))} onChange={set('from')} />
      </FormGroup>
    </FlexBox>
  );
}
