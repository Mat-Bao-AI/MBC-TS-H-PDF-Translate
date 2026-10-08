import { vi } from 'vitest';

export type Reply = { status?: number; body?: unknown };
export type Handler = Reply | ((request: { url: string; init: RequestInit }) => Reply);
export type Call = { method: string; url: string; body: BodyInit | null | undefined; headers: Headers };

export function sequence(...replies: Reply[]): Handler {
  let index = 0;
  return () => replies[Math.min(index++, replies.length - 1)];
}

export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const method = (init.method ?? 'GET').toUpperCase();
    calls.push({ method, url, body: init.body, headers: new Headers(init.headers) });
    const handler = routes[`${method} ${url}`] ?? routes[`${method} ${url.split('?')[0]}`];
    if (!handler) {
      return new Response(JSON.stringify({ detail: { code: 'unmocked', url } }), { status: 500 });
    }
    const { status = 200, body } = typeof handler === 'function' ? handler({ url, init }) : handler;
    return new Response(status === 204 ? null : JSON.stringify(body ?? {}), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

/** Giữ lại mọi GET tới `url` (khớp tiền tố) cho tới khi gọi `release()`: để quan sát trạng thái "đang tải". */
export function holdRequests(fetchMock: ReturnType<typeof mockApi>['fetchMock'], url: string) {
  const original = fetchMock.getMockImplementation()!;
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  fetchMock.mockImplementation(async (input, init) => {
    const target = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    if (target.startsWith(url)) await gate;
    return original(input, init);
  });
  return { release };
}
