import { describe, expect, it } from 'vitest';
import { t } from '../i18n/t';
import { formatRelative } from '../lib/relativeTime';
import { META, fileItem, fileVersion, snapshot } from '../test/fixtures';
import { configRows, currentEntry, entriesOf, entryHeadline, entryTime, frameUrl, languageNamer } from './versions';

const nameOf = languageNamer(META);

describe('configRows', () => {
  it('describes a basic translation with "Cơ bản" and dashes', () => {
    const rows = configRows(currentEntry(fileItem()), META, nameOf);
    expect(rows.map((row) => row.key)).toEqual(['language', 'engine', 'font', 'profile', 'fidelity', 'tone', 'audience', 'terms', 'proper_names',
      'numbers', 'dates', 'abbreviations', 'custom_instructions', 'context']);
    expect(rows[0].value).toBe('Tiếng Việt');
    expect(rows[1].value).toBe('Google miễn phí');
    expect(rows[3].value).toBe(t('detail.version.basic'));
    expect(rows[5].value).toBe(t('detail.config.none'));
  });

  it('spells out a snapshot in Vietnamese labels', () => {
    const entry = { ...currentEntry(fileItem({ engine: 'gemini', model: 'gemini-3.8-flash', language: 'en', font_used: 'serif' })),
      config: snapshot({ style: { ...snapshot().style, tone: 'friendly' }, overrides: ['tone'], document_context: 'API' }) };
    const rows = configRows(entry, META, nameOf);
    expect(rows[0].value).toBe('Tiếng Anh');
    expect(rows[1].value).toBe('Gemini 3.8 Flash');
    expect(rows[2].value).toBe(t('font.used.serif'));
    expect(rows[3].value).toBe('Tài liệu kỹ thuật');
    expect(rows[5].value).toBe(t('profiles.value.tone.friendly'));
    expect(rows[12].value).toBe(snapshot().style!.custom_instructions);
    expect(rows[13].value).toBe('API');
    expect(configRows({ ...entry, config: fileVersion().config }, META, nameOf)[13].value).toBe(t('detail.config.none'));
  });
});

describe('entries, time and headline', () => {
  it('orders versions oldest first with the current one last and falls back to the archive time only when the translation time is unknown', () => {
    const item = fileItem({ version_no: 3, translated_at: '2026-10-15T10:00:00Z', versions: [
      fileVersion({ id: 'v2', version_no: 2, translated_at: '2026-10-14T10:00:00Z', archived_at: '2026-10-15T09:00:00Z' }),
      fileVersion({ id: 'v1', version_no: 1, translated_at: null, archived_at: '2026-10-13T08:00:00Z' }),
    ] });
    const entries = entriesOf(item);
    expect(entries.map((entry) => [entry.id, entry.version_no])).toEqual([['v1', 1], ['v2', 2], [null, 3]]);
    expect(entryTime(entries[0])).toBe(t('versions.archivedAt', { time: formatRelative('2026-10-13T08:00:00Z') }));
    expect(entryTime(entries[1])).toBe(formatRelative('2026-10-14T10:00:00Z'));
    expect(entryHeadline(entries[2], META)).toBe([
      t('detail.version.label', { n: 3 }), formatRelative('2026-10-15T10:00:00Z'), 'Google miễn phí', t('detail.version.basic'), t('detail.version.current'),
    ].join(' · '));
  });

  it('names the version a restored copy came from and the profile of a snapshot', () => {
    const entry = currentEntry(fileItem({ version_no: 4, restored_from: 1, engine: 'gemini', model: 'gemini-3.8-flash', config: snapshot() }));
    expect(entryHeadline(entry, META)).toContain(`Gemini 3.8 Flash · Tài liệu kỹ thuật · ${t('detail.restoredFrom', { k: 1 })} · ${t('detail.version.current')}`);
  });

  it('uses the version route for an old version and a cache-busted view URL for the current translation', () => {
    const item = fileItem({ id: 'f1', finished_at: '2026-10-02T10:00:00Z' });
    expect(frameUrl(item, 'translated', 'v1')).toBe('/api/files/f1/versions/v1/download?inline=1');
    expect(frameUrl(item, 'translated', null)).toBe('/api/files/f1/download?kind=translated&inline=1&v=2026-10-02T10%3A00%3A00Z');
    expect(frameUrl(item, 'original', 'v1')).toBe('/api/files/f1/download?kind=original&inline=1');
  });
});
