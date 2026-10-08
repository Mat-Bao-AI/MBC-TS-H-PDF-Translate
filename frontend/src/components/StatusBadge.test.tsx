import { describe, expect, it } from 'vitest';
import { t } from '../i18n/t';
import { fileItem } from '../test/fixtures';
import { statusLabel } from './StatusBadge';

describe('statusLabel', () => {
  it('shows the step and its progress for a handoff job instead of a percentage that restarts per step', () => {
    const running = { status: 'running' as const, engine: 'gemini', model: 'gemini-3.5-flash-lite' };
    expect(statusLabel(fileItem({ ...running, stage: 'split', done_pages: 1, total_pages: 4 }))).toBe('Bước 1/3 · 25%');
    expect(statusLabel(fileItem({ ...running, stage: 'translate', done_pages: 3, total_pages: 10 }))).toBe('Bước 2/3 · 30%');
    expect(statusLabel(fileItem({ ...running, stage: 'render', done_pages: 0, total_pages: 0 }))).toBe('Bước 3/3 · 0%');
  });

  it('keeps the plain percentage for Google free and the plain labels otherwise', () => {
    expect(statusLabel(fileItem({ status: 'running', stage: '', done_pages: 1, total_pages: 2 }))).toBe(t('status.runningPct', { pct: 50 }));
    expect(statusLabel(fileItem({ status: 'running', stage: '', done_pages: 0, total_pages: 0 }))).toBe(t('status.running'));
    expect(statusLabel(fileItem({ status: 'queued', stage: '' }))).toBe(t('status.queued'));
    expect(statusLabel(fileItem({ status: 'done', stage: '' }))).toBe(t('status.done'));
  });
});
