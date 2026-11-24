import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sdkLogin = vi.hoisted(() => vi.fn());
vi.mock('./sdk', () => ({ login: sdkLogin }));

const loginResponse = (token: string) => ({ token, open_id: 'u1', token_type: 'Bearer', expires_in: 604800 });

let stored: Map<string, string>;
let fetchMock: ReturnType<typeof vi.fn>;

function response(status: number, data: unknown): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
}

function authenticated(init?: RequestInit): string | null {
  return new Headers(init?.headers).get('Authorization');
}

beforeEach(() => {
  vi.resetModules();
  sdkLogin.mockReset().mockResolvedValue('fresh-code');
  stored = new Map();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value),
    removeItem: (key: string) => stored.delete(key),
  });
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Minis backend session', () => {
  it('shares one initial login among concurrent requests and never caches the code', async () => {
    fetchMock.mockImplementation(async (url: string) => url.endsWith('/auth/login')
      ? response(200, { token: 'session', open_id: 'u1', token_type: 'Bearer', expires_in: 604800 })
      : response(200, { open_id: 'u1' }));
    const { apiFetch } = await import('./session');
    await Promise.all([apiFetch('/auth/me'), apiFetch('/auth/me'), apiFetch('/auth/me')]);
    expect(sdkLogin).toHaveBeenCalledTimes(1);
    const requests = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/auth/login'));
    expect(requests).toHaveLength(1);
    expect(JSON.parse(requests[0][1].body)).toEqual({ code: 'fresh-code' });
    expect([...stored.values()]).toEqual(['session']);
  });

  it('uses the cached session without calling the SDK', async () => {
    stored.set('sailreels_session', 'cached');
    fetchMock.mockResolvedValue(response(200, { open_id: 'u1' }));
    const { getSessionProfile } = await import('./session');
    expect(await getSessionProfile()).toEqual({ open_id: 'u1' });
    expect(authenticated(fetchMock.mock.calls[0][1])).toBe('Bearer cached');
    expect(sdkLogin).not.toHaveBeenCalled();
  });

  it('concurrent 401s establish one new session and retry each request once', async () => {
    stored.set('sailreels_session', 'expired');
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/login')) return response(200, loginResponse('renewed'));
      return authenticated(init) === 'Bearer expired'
        ? response(401, { detail: 'login_required' }) : response(200, { ok: true });
    });
    const { apiFetch } = await import('./session');
    expect(await Promise.all([apiFetch('/one'), apiFetch('/two'), apiFetch('/three')]))
      .toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(sdkLogin).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(7);
  });

  it('a late 401 for the previous session reuses the renewed session', async () => {
    stored.set('sailreels_session', 'expired');
    let finishLate: (value: Response) => void = () => { throw new Error('No pending request'); };
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/login')) return response(200, loginResponse('renewed'));
      if (authenticated(init) === 'Bearer renewed') return response(200, { ok: true });
      if (url.endsWith('/late')) return new Promise<Response>((resolve) => { finishLate = resolve; });
      return response(401, { detail: 'login_required' });
    });
    const { apiFetch } = await import('./session');
    const first = apiFetch('/first');
    const late = apiFetch('/late');
    await first;
    finishLate(response(401, { detail: 'login_required' }));
    expect(await late).toEqual({ ok: true });
    expect(sdkLogin).toHaveBeenCalledTimes(1);
  });

  it('stops after a second 401 and discards the rejected session', async () => {
    stored.set('sailreels_session', 'expired');
    fetchMock.mockImplementation(async (url: string) => url.endsWith('/auth/login')
      ? response(200, loginResponse('still-invalid')) : response(401, { detail: 'login_required' }));
    const { apiFetch } = await import('./session');
    await expect(apiFetch('/auth/me')).rejects.toMatchObject({ status: 401, detail: 'login_required' });
    expect(sdkLogin).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(stored.has('sailreels_session')).toBe(false);
  });

  it('preserves POST body, method and Headers during the single 401 retry', async () => {
    stored.set('sailreels_session', 'expired');
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/login')) return response(200, loginResponse('renewed'));
      return response(authenticated(init) === 'Bearer expired' ? 401 : 200, { ok: true });
    });
    const { apiFetch } = await import('./session');
    await apiFetch('/orders/beans', {
      method: 'POST', body: '{"drama_id":1,"seq":6}', headers: new Headers({ 'X-Trace': 'trace' }),
    });
    for (const [, init] of fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/orders/beans'))) {
      expect(init.method).toBe('POST');
      expect(init.body).toBe('{"drama_id":1,"seq":6}');
      expect(new Headers(init.headers).get('X-Trace')).toBe('trace');
    }
  });

  it.each([403, 429, 502, 503, 504])('does not re-login on HTTP %i', async (status) => {
    stored.set('sailreels_session', 'cached');
    fetchMock.mockResolvedValue(response(status, { detail: 'tiktok_unavailable' }));
    const { apiFetch } = await import('./session');
    await expect(apiFetch('/auth/me')).rejects.toMatchObject({ status });
    expect(sdkLogin).not.toHaveBeenCalled();
    expect(stored.get('sailreels_session')).toBe('cached');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clears stale state after failed re-login and allows a later fresh attempt', async () => {
    stored.set('sailreels_session', 'expired');
    sdkLogin.mockRejectedValueOnce(new Error('SDK unavailable'));
    fetchMock.mockResolvedValueOnce(response(401, { detail: 'login_required' }));
    const { apiFetch, ensureSession } = await import('./session');
    await expect(apiFetch('/auth/me')).rejects.toThrow('SDK unavailable');
    expect(stored.has('sailreels_session')).toBe(false);
    fetchMock.mockResolvedValue(response(200, loginResponse('renewed')));
    expect(await ensureSession()).toBe('renewed');
    expect(sdkLogin).toHaveBeenCalledTimes(2);
  });

  it('does not replay a failed one-time code exchange', async () => {
    fetchMock.mockResolvedValue(response(400, { detail: 'invalid_login_code' }));
    const { ensureSession } = await import('./session');
    await expect(ensureSession()).rejects.toMatchObject({ status: 400, detail: 'invalid_login_code' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(stored.size).toBe(0);
  });

  it('aborts a stalled code exchange and allows a later fresh login', async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }));
    const { ensureSession } = await import('./session');
    const failure = expect(ensureSession()).rejects.toThrow('aborted');
    await vi.advanceTimersByTimeAsync(20_000);
    await failure;
    expect(stored.size).toBe(0);
    fetchMock.mockResolvedValue(response(200, loginResponse('renewed')));
    expect(await ensureSession()).toBe('renewed');
    expect(sdkLogin).toHaveBeenCalledTimes(2);
  });

  it('preserves a bounded business order reference on errors without exposing provider diagnostics', async () => {
    stored.set('sailreels_session', 'cached');
    fetchMock.mockResolvedValue(response(504, { detail: 'tiktok_timeout', order_id: 'b_uncertain',
      access_token: 'private-provider-token', debug: 'private-diagnostics' }));
    const { apiFetch } = await import('./session');
    await expect(apiFetch('/orders/beans', { method: 'POST' })).rejects.toMatchObject({
      status: 504, detail: 'tiktok_timeout', orderId: 'b_uncertain',
    });
    fetchMock.mockResolvedValue(response(502, { detail: 'private-diagnostics', order_id: 'invalid/order' }));
    await expect(apiFetch('/orders/beans', { method: 'POST' })).rejects.toMatchObject({
      status: 502, detail: 'request_failed', orderId: undefined,
    });
  });
});
