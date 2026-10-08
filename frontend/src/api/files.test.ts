import { describe, expect, it } from 'vitest';
import { mockApi } from '../test/mockApi';
import { filesApi } from './files';

describe('filesApi.bulkDelete', () => {
  it('posts the ids with the CSRF header', async () => {
    const { calls } = mockApi({ 'POST /api/files/bulk-delete': { body: { deleted: 2, skipped_running: 0 } } });
    expect(await filesApi.bulkDelete({ ids: ['a', 'b'] })).toEqual({ deleted: 2, skipped_running: 0 });
    expect(JSON.parse(String(calls[0].body))).toEqual({ ids: ['a', 'b'] });
    expect(calls[0].headers.get('X-Requested-With')).toBe('fetch');
  });

  it('posts "all" together with the filter', async () => {
    const { calls } = mockApi({ 'POST /api/files/bulk-delete': { body: { deleted: 5, skipped_running: 1 } } });
    await filesApi.bulkDelete({ all: true, q: 'seed' });
    expect(JSON.parse(String(calls[0].body))).toEqual({ all: true, q: 'seed' });
  });
});

describe('filesApi.retranslate / bulkRetranslate', () => {
  it('posts the four choices of one file with the CSRF header', async () => {
    const { calls } = mockApi({ 'POST /api/files/f1/retranslate': { status: 202, body: {} } });
    await filesApi.retranslate('f1', { language: 'en', engine: 'google_free', model: null, font: 'serif' });
    expect(JSON.parse(String(calls[0].body))).toEqual({ language: 'en', engine: 'google_free', model: null, font: 'serif' });
    expect(calls[0].headers.get('X-Requested-With')).toBe('fetch');
  });

  it('posts the selection together with the shared settings or null', async () => {
    const { calls } = mockApi({ 'POST /api/files/bulk-retranslate': { body: { queued: 2, skipped_pending: 1, skipped_limit: 0, limit: 3 } } });
    expect(await filesApi.bulkRetranslate({ all: true, q: 'seed', settings: null }))
      .toEqual({ queued: 2, skipped_pending: 1, skipped_limit: 0, limit: 3 });
    await filesApi.bulkRetranslate({ ids: ['a'], settings: { language: 'vi', engine: 'gemini', model: 'gemini-3.8-flash', font: 'auto' } });
    expect(calls.map((call) => JSON.parse(String(call.body)))).toEqual([
      { all: true, q: 'seed', settings: null },
      { ids: ['a'], settings: { language: 'vi', engine: 'gemini', model: 'gemini-3.8-flash', font: 'auto' } },
    ]);
  });
});
