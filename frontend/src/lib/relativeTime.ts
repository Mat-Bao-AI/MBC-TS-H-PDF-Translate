import { t, type MessageKey } from '../i18n/t';

const DAY = 24 * 60 * 60 * 1000;
const pad = (value: number) => String(value).padStart(2, '0');
const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

export function formatRelative(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const days = Math.round((startOfDay(now) - startOfDay(date)) / DAY);
  if (days <= 0) return t('time.today', { time });
  if (days === 1) return t('time.yesterday', { time });
  if (days < 7) return t('time.weekday', { day: t(`weekday.${date.getDay()}` as MessageKey), time });
  const year = date.getFullYear() === now.getFullYear() ? '' : `/${date.getFullYear()}`;
  return `${date.getDate()}/${date.getMonth() + 1}${year}`;
}
