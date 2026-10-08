import { startTransition, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, Card, Dialog, FillButton, FlexBox, FormGroup, Input, Text } from '@codecademy/gamut';
import { accountApi } from '../../api/account';
import type { Me } from '../../api/auth';
import { toApiError, type ApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { emailError, passwordError } from '../../auth/validate';
import { errorText, t } from '../../i18n/t';
import { RouterAnchor } from '../../components/RouterAnchor';

type FieldErrors<F extends string> = Partial<Record<F, string>>;

/**
 * Trạng thái chung của một form tài khoản: đang gửi, lỗi chung (Alert), lỗi theo ô (dưới ô), xong.
 * `fieldOf` ánh xạ mã lỗi của server → ô nhận lỗi; `local` là lỗi kiểm ngay trên trình duyệt (có lỗi → không gọi API).
 */
function useAccountForm<F extends string>(fieldOf: Partial<Record<string, F>>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<F>>({});
  const [done, setDone] = useState(false);
  // Ref chứ không chỉ state: hai lần bấm liền nhau có thể tới trước lần render đã cập nhật `busy`.
  const inFlight = useRef(false);

  function clear() {
    setError(null);
    setFieldErrors({});
    setDone(false);
  }

  async function run(action: () => Promise<void>, local: Partial<Record<F, string | undefined>> = {}) {
    if (inFlight.current) return;
    const problems = Object.fromEntries(Object.entries(local).filter(([, message]) => message)) as FieldErrors<F>;
    clear();
    setFieldErrors(problems);
    if (Object.keys(problems).length > 0) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await action();
      setDone(true);
    } catch (caught) {
      const apiError = toApiError(caught);
      const field = fieldOf[apiError.code];
      if (field) setFieldErrors({ [field]: errorText(apiError.code) } as FieldErrors<F>);
      else setError(apiError);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return { busy, error, fieldErrors, done, clear, run };
}

/** Một thẻ = một `<section>` mang tên theo tiêu đề (role "region"): test và E2E tìm ô trong đúng thẻ. */
function AccountCard({ title, danger = false, children }: { title: string; danger?: boolean; children: ReactNode }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <Card p={24} borderColor={danger ? 'feedback-error' : undefined}>
        <Text as="h2" id={headingId} variant="title-xs" mb={16}>{title}</Text>
        {children}
      </Card>
    </section>
  );
}

function FormAlerts({ error, success }: { error: ApiError | null; success: string | null }) {
  return (
    <>
      {error && <Alert type="error" placement="inline">{errorText(error.code, error.params)}</Alert>}
      {success && <Alert type="success" placement="inline">{success}</Alert>}
    </>
  );
}

function DisplayNameCard({ user }: { user: Me }) {
  const { signedIn } = useAuth();
  const [name, setName] = useState(user.display_name ?? '');
  const form = useAccountForm({ invalid_display_name: 'name' });

  function submit(event: FormEvent) {
    event.preventDefault();
    void form.run(async () => {
      const me = await accountApi.saveProfile(name);
      signedIn(me); // avatar + lời chào đổi ngay
      setName(me.display_name ?? '');
    });
  }

  return (
    <AccountCard title={t('account.name.title')}>
      <form onSubmit={submit} noValidate>
        <FlexBox flexDirection="column" gap={16}>
          <FormGroup label={t('account.name.label')} htmlFor="account-name" description={t('account.name.hint')}
            error={form.fieldErrors.name} isSoloField>
            <Input id="account-name" value={name} maxLength={50} autoComplete="nickname"
              error={Boolean(form.fieldErrors.name)} onChange={(event) => setName(event.target.value)} />
          </FormGroup>
          <FormAlerts error={form.error} success={form.done ? t('account.name.saved') : null} />
          <Box><FillButton type="submit" disabled={form.busy}>{t('account.name.submit')}</FillButton></Box>
        </FlexBox>
      </form>
    </AccountCard>
  );
}

function EmailCard() {
  const { user, instance } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [sentTo, setSentTo] = useState('');
  const form = useAccountForm({ invalid_email: 'email', same_email: 'email', wrong_password: 'password' });

  function submit(event: FormEvent) {
    event.preventDefault();
    const target = email.trim();
    void form.run(async () => {
      await accountApi.requestEmailChange(target, password);
      setSentTo(target); // cùng một câu dù email mới đã có người dùng hay chưa (server luôn trả 202)
      setEmail('');
      setPassword('');
    }, { email: emailError(target) });
  }

  return (
    <AccountCard title={t('account.email.title')}>
      {instance && !instance.mail_enabled ? (
        <FlexBox flexDirection="column" gap={16} alignItems="flex-start">
          <Text>{t('account.email.noMail')}</Text>
          {user?.is_admin && <RouterAnchor to="/settings/system">{t('account.email.configureSmtp')}</RouterAnchor>}
        </FlexBox>
      ) : (
        <form onSubmit={submit} noValidate>
          <FlexBox flexDirection="column" gap={16}>
            <FormGroup label={t('account.email.label')} htmlFor="account-new-email" error={form.fieldErrors.email} isSoloField>
              <Input id="account-new-email" type="email" autoComplete="email" value={email}
                error={Boolean(form.fieldErrors.email)} onChange={(event) => setEmail(event.target.value)} />
            </FormGroup>
            <FormGroup label={t('field.currentPassword')} htmlFor="account-email-password" error={form.fieldErrors.password}
              isSoloField>
              <Input id="account-email-password" type="password" autoComplete="current-password" value={password}
                error={Boolean(form.fieldErrors.password)} onChange={(event) => setPassword(event.target.value)} />
            </FormGroup>
            <FormAlerts error={form.error} success={form.done ? t('account.email.sent', { email: sentTo }) : null} />
            <Box><FillButton type="submit" disabled={form.busy}>{t('account.email.submit')}</FillButton></Box>
          </FlexBox>
        </form>
      )}
    </AccountCard>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const form = useAccountForm<'current' | 'next' | 'confirm'>({ wrong_password: 'current', invalid_password: 'next' });

  function submit(event: FormEvent) {
    event.preventDefault();
    void form.run(async () => {
      await accountApi.changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
    }, {
      next: passwordError(next),
      confirm: next !== confirm ? t('account.password.mismatch') : undefined,
    });
  }

  return (
    <AccountCard title={t('account.password.title')}>
      <form onSubmit={submit} noValidate>
        <FlexBox flexDirection="column" gap={16}>
          <FormGroup label={t('field.currentPassword')} htmlFor="account-current-password" error={form.fieldErrors.current}
            isSoloField>
            <Input id="account-current-password" type="password" autoComplete="current-password" value={current}
              error={Boolean(form.fieldErrors.current)} onChange={(event) => setCurrent(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('field.newPassword')} htmlFor="account-new-password" description={t('field.passwordHint')}
            error={form.fieldErrors.next} isSoloField>
            <Input id="account-new-password" type="password" autoComplete="new-password" value={next}
              error={Boolean(form.fieldErrors.next)} onChange={(event) => setNext(event.target.value)} />
          </FormGroup>
          <FormGroup label={t('field.confirmPassword')} htmlFor="account-confirm-password" error={form.fieldErrors.confirm}
            isSoloField>
            <Input id="account-confirm-password" type="password" autoComplete="new-password" value={confirm}
              error={Boolean(form.fieldErrors.confirm)} onChange={(event) => setConfirm(event.target.value)} />
          </FormGroup>
          <FormAlerts error={form.error} success={form.done ? t('account.password.done') : null} />
          <Box><FillButton type="submit" disabled={form.busy}>{t('account.password.submit')}</FillButton></Box>
        </FlexBox>
      </form>
    </AccountCard>
  );
}

function DangerZoneCard() {
  const navigate = useNavigate();
  const { signedOut, refreshInstance } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const form = useAccountForm({ wrong_password: 'password' });

  function close() {
    setOpen(false);
    setPassword('');
    form.clear();
  }

  function confirmDelete() {
    if (form.done) return; // đã xoá xong, đang chờ chuyển trang: bấm thêm sẽ gửi lệnh xoá lần hai
    void form.run(async () => {
      await accountApi.deleteAccount(password); // server đã huỷ phiên + xoá cookie
      // CÙNG một transition với lần điều hướng (React Router đổi location trong startTransition): tách ra thì
      // RequireAuth kịp render với user = null ở /settings/account và tự đưa về /login?next=… thay vì ?deleted=1.
      startTransition(() => {
        signedOut();
        navigate('/login?deleted=1', { replace: true });
      });
      // Tài khoản cuối cùng vừa đi → instance cần cài đặt lại: guard của /login đưa tới /setup, không cần tải lại trang.
      void refreshInstance();
    });
  }

  return (
    <AccountCard title={t('account.danger.title')} danger>
      <FlexBox flexDirection="column" gap={16}>
        <Text>{t('account.danger.body')}</Text>
        <Box>
          <FillButton type="button" variant="danger" onClick={() => setOpen(true)}>{t('account.danger.open')}</FillButton>
        </Box>
      </FlexBox>
      <Dialog
        isOpen={open}
        title={t('account.danger.dialogTitle')}
        variant="danger"
        // Dialog gọi onRequestClose cả khi bấm nút xác nhận → để trống, hộp thoại còn mở khi sai mật khẩu.
        // Huỷ / nút X / Esc / bấm ra ngoài đều đi qua cancelCta.onClick (Dialog tự gọi cho cả bốn).
        onRequestClose={() => undefined}
        confirmCta={{ children: t('account.danger.confirm'), onClick: confirmDelete }}
        cancelCta={{ children: t('common.cancel'), onClick: close }}
      >
        <FlexBox flexDirection="column" gap={16}>
          <Text>{t('account.danger.dialogBody')}</Text>
          <FormGroup label={t('field.currentPassword')} htmlFor="account-delete-password" error={form.fieldErrors.password}
            isSoloField>
            <Input id="account-delete-password" type="password" autoComplete="current-password" value={password}
              error={Boolean(form.fieldErrors.password)} onChange={(event) => setPassword(event.target.value)} />
          </FormGroup>
          {form.error && (
            <Alert type="error" placement="inline">
              {errorText(form.error.code, form.error.params)}
              {form.error.code === 'file_running' && ` ${t('account.danger.fileRunning')}`}
            </Alert>
          )}
        </FlexBox>
      </Dialog>
    </AccountCard>
  );
}

/** Cài đặt › Tài khoản: bốn thẻ, mỗi thẻ một form độc lập. */
export function AccountSettingsPage() {
  const { user } = useAuth();
  if (!user) return null; // RequireAuth đã chặn ở ngoài; nhánh này chỉ để TypeScript yên tâm
  return (
    <FlexBox flexDirection="column" gap={24}>
      <Text color="text-secondary">{t('account.signedInAs', { email: user.email })}</Text>
      <DisplayNameCard user={user} />
      <EmailCard />
      <PasswordCard />
      <DangerZoneCard />
    </FlexBox>
  );
}
