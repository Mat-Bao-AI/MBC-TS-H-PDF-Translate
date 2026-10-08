import { errorText } from '../i18n/t';

export type FieldErrors = { email?: string; password?: string };

/** Mã lỗi server nào thuộc về ô nào — để hiện lỗi ngay dưới ô thay vì ở đầu form. */
export const FIELD_OF: Record<string, keyof FieldErrors> = { invalid_email: 'email', invalid_password: 'password' };

export function emailError(email: string): string | undefined {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) ? undefined : errorText('invalid_email');
}

export function passwordError(password: string): string | undefined {
  return password.length >= 8 && password.length <= 128 ? undefined : errorText('invalid_password');
}

export function validateCredentials(email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  const emailProblem = emailError(email);
  const passwordProblem = passwordError(password);
  if (emailProblem) errors.email = emailProblem;
  if (passwordProblem) errors.password = passwordProblem;
  return errors;
}
