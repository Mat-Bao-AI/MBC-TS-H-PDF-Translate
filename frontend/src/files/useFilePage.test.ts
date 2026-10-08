import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { fileItem, filePage } from '../test/fixtures';
import { cacheClear } from '../lib/swrCache';
import { mockApi } from '../test/mockApi';
import { useFilePage } from './useFilePage';

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

describe('useFilePage', () => {
  it('ignores a slow response for an old query', async () => {
    const pending: Record<string, (response: Response) => void> = {};
    vi.stubGlobal('fetch', vi.fn((url: string) => new Promise<Response>((resolve) => {
      pending[new URL(url, 'http://x').searchParams.get('q') ?? ''] = resolve;
    })));
    const { result, rerender } = renderHook(({ q }) => useFilePage(q, 1), { initialProps: { q: '' } });
    rerender({ q: 'moi' });
    await waitFor(() => expect(pending.moi).toBeDefined());
    await act(async () => pending.moi(json(filePage([fileItem({ filename: 'moi.pdf' })]))));
    await waitFor(() => expect(result.current.data?.items[0].filename).toBe('moi.pdf'));
    await act(async () => pending[''](json(filePage([fileItem({ filename: 'cu.pdf' })]))));
    expect(result.current.data?.items[0].filename).toBe('moi.pdf');
  });

  it('polls every 3 seconds while a file is pending', async () => {
    // Fake timers WITHOUT `shouldAdvanceTime`: that flag ties the fake clock to real wall-clock
    // time, which raced with interval registration under CPU load (flaky ~1/10 runs in the full
    // suite). Flushing the initial fetch's promise chain by hand keeps this load-independent.
    vi.useFakeTimers();
    const { calls } = mockApi({ 'GET /api/files': { body: filePage([fileItem({ status: 'running' })]) } });
    renderHook(() => useFilePage('', 1));
    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(calls).toHaveLength(1);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(calls.length).toBeGreaterThanOrEqual(2);
  });

  it('sends the sort params and keeps them on every poll', async () => {
    vi.useFakeTimers();
    const { calls } = mockApi({ 'GET /api/files': { body: filePage([fileItem({ status: 'queued' })]) } });
    renderHook(() => useFilePage('abc', 2, 'name', 'asc'));
    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(calls.length).toBeGreaterThanOrEqual(2);
    for (const call of calls) {
      const params = new URL(call.url, 'http://x').searchParams;
      expect([params.get('q'), params.get('page'), params.get('sort'), params.get('dir')]).toEqual(['abc', '2', 'name', 'asc']);
    }
  });

  it('defaults to created / desc', async () => {
    const { calls } = mockApi({ 'GET /api/files': { body: filePage([]) } });
    renderHook(() => useFilePage('', 1));
    await waitFor(() => expect(calls).toHaveLength(1));
    const params = new URL(calls[0].url, 'http://x').searchParams;
    expect([params.get('sort'), params.get('dir')]).toEqual(['created', 'desc']);
  });
});

describe('useFilePage cache', () => {
  it('serves the cached page at once on a revisit, then refreshes it in the background', async () => {
    mockApi({ 'GET /api/files': { body: filePage([fileItem({ filename: 'cu.pdf' })]) } });
    const first = renderHook(() => useFilePage('', 1));
    await waitFor(() => expect(first.result.current.data?.items[0].filename).toBe('cu.pdf'));
    first.unmount();

    let release: (response: Response) => void = () => undefined;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve; })));
    const second = renderHook(() => useFilePage('', 1));
    expect(second.result.current.data?.items[0].filename).toBe('cu.pdf'); // lượt render đầu, chưa có phản hồi
    await act(async () => release(json(filePage([fileItem({ filename: 'moi.pdf' })]))));
    await waitFor(() => expect(second.result.current.data?.items[0].filename).toBe('moi.pdf'));
  });

  it('keys the cache by query, page and sort', async () => {
    mockApi({ 'GET /api/files': { body: filePage([fileItem({ filename: 'a.pdf' })]) } });
    const first = renderHook(() => useFilePage('a', 1));
    await waitFor(() => expect(first.result.current.data).not.toBeNull());
    first.unmount();
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
    expect(renderHook(() => useFilePage('b', 1)).result.current.data).toBeNull();
    expect(renderHook(() => useFilePage('a', 2)).result.current.data).toBeNull();
    expect(renderHook(() => useFilePage('a', 1, 'name', 'asc')).result.current.data).toBeNull();
    expect(renderHook(() => useFilePage('a', 1)).result.current.data).not.toBeNull();
  });

  it('starts empty again after the caches are cleared', async () => {
    mockApi({ 'GET /api/files': { body: filePage([fileItem()]) } });
    const first = renderHook(() => useFilePage('', 1));
    await waitFor(() => expect(first.result.current.data).not.toBeNull());
    first.unmount();
    cacheClear();
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
    expect(renderHook(() => useFilePage('', 1)).result.current.data).toBeNull();
  });
});
