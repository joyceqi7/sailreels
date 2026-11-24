import assert from 'node:assert/strict';
import { after, before, beforeEach, test } from 'node:test';
import { createServer } from 'vite';
import { createServer as createHttpServer } from 'node:http';

let server;
let session;
let sequence = 0;
let values;
let loginCalls;
const originalFetch = globalThis.fetch;
const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const loginResponse = (token = 'test-session') => ({ token, open_id: 'test-user', token_type: 'Bearer', expires_in: 604800 });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

before(async () => {
  server = await createServer({
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: { server: createHttpServer() }, watch: null }, appType: 'custom',
  });
});

beforeEach(async () => {
  values = new Map();
  loginCalls = 0;
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    TTMinis: { login: callback => {
      loginCalls++;
      callback({ authResponse: { code: `test-code-${loginCalls}` } });
    } },
  } });
  globalThis.fetch = async url => { throw new Error(`Unexpected test request: ${url}`); };
  // Each test gets a fresh session module, including its in-memory token.
  session = await server.ssrLoadModule(`/src/minis/session.ts?test=${++sequence}`);
});

after(async () => {
  globalThis.fetch = originalFetch;
  if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
  else delete globalThis.window;
  if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
  else delete globalThis.localStorage;
  await server?.close();
});

test('startup exchanges one code, stores only the app session and verifies /me', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push(url);
    if (url.endsWith('/auth/login')) {
      assert.deepEqual(JSON.parse(init.body), { code: 'test-code-1' });
      assert.equal(init.cache, 'no-store');
      return json(loginResponse('test-session'));
    }
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer test-session');
    return json({ open_id: 'test-user', nickname: null, avatar_url: null });
  };
  await session.initializeSession();
  assert.deepEqual(calls, ['/api/v1/auth/login', '/api/v1/auth/me']);
  assert.deepEqual([...values], [['sailreels_session', 'test-session']]);
  assert.equal(loginCalls, 1);
});

test('a persisted session is checked with the backend without requesting a new code', async () => {
  values.set('sailreels_session', 'persisted-test-session');
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/v1/auth/me');
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer persisted-test-session');
    return json({ open_id: 'test-user' });
  };
  await session.initializeSession();
  assert.equal(loginCalls, 0);
});

test('concurrent initial logins share one code exchange', async () => {
  const exchange = deferred();
  let requests = 0;
  globalThis.fetch = async () => { requests++; return exchange.promise; };
  const attempts = [session.ensureSession(), session.ensureSession(), session.ensureSession()];
  exchange.resolve(json(loginResponse('test-session')));
  assert.deepEqual(await Promise.all(attempts), Array(3).fill('test-session'));
  assert.equal(requests, 1);
  assert.equal(loginCalls, 1);
});

test('a delayed old-token 401 reuses the session another request already refreshed', async () => {
  values.set('sailreels_session', 'expired-test-session');
  const oldResponses = [];
  const bothStarted = deferred();
  globalThis.fetch = async (url, init) => {
    if (url.endsWith('/auth/login')) return json(loginResponse('fresh-test-session'));
    if (new Headers(init.headers).get('Authorization') === 'Bearer expired-test-session') {
      const response = deferred();
      oldResponses.push(response);
      if (oldResponses.length === 2) bothStarted.resolve();
      return response.promise;
    }
    return json({ ok: true });
  };
  const first = session.apiFetch('/first');
  const second = session.apiFetch('/second');
  await bothStarted.promise;
  oldResponses[0].resolve(json({}, 401));
  await first;
  oldResponses[1].resolve(json({}, 401));
  await second;
  assert.equal(loginCalls, 1);
});

test('overlapping 401s and ordinary callers wait for the same in-flight refresh', async () => {
  values.set('sailreels_session', 'expired-test-session');
  const exchange = deferred();
  const loginStarted = deferred();
  globalThis.fetch = async (url, init) => {
    if (url.endsWith('/auth/login')) { loginStarted.resolve(); return exchange.promise; }
    return new Headers(init.headers).get('Authorization') === 'Bearer expired-test-session'
      ? json({}, 401) : json({ ok: true });
  };
  const requests = [session.apiFetch('/first'), session.apiFetch('/second')];
  await loginStarted.promise;
  const ordinaryCaller = session.ensureSession();
  exchange.resolve(json(loginResponse('fresh-test-session')));
  await Promise.all(requests);
  assert.equal(await ordinaryCaller, 'fresh-test-session');
  assert.equal(loginCalls, 1);
});

test('a second 401 stops retrying and removes the rejected session', async () => {
  values.set('sailreels_session', 'expired-test-session');
  let protectedRequests = 0;
  globalThis.fetch = async url => {
    if (url.endsWith('/auth/login')) return json(loginResponse('rejected-test-session'));
    protectedRequests++;
    return json({ detail: 'not for display' }, 401);
  };
  await assert.rejects(session.apiFetch('/protected'), /failed \(401\)/);
  assert.equal(protectedRequests, 2);
  assert.equal(loginCalls, 1);
  assert.equal(values.has('sailreels_session'), false);
});

test('a failed exchange can be retried with a new one-time code', async () => {
  const codes = [];
  globalThis.fetch = async (_url, init) => {
    codes.push(JSON.parse(init.body).code);
    return codes.length === 1 ? json({}, 400) : json(loginResponse('test-session'));
  };
  await assert.rejects(session.ensureSession(), { status: 400, detail: 'request_failed' });
  assert.equal(values.size, 0);
  assert.equal(await session.ensureSession(), 'test-session');
  assert.deepEqual(codes, ['test-code-1', 'test-code-2']);
});

test('invalid successful login payloads do not persist a session', async () => {
  for (const body of [null, {}, { token: '' }, { token: 'test-session' }, { token: 12, open_id: 'user' },
    { token: 'session', open_id: 'user' }, { ...loginResponse(), expires_in: 0 },
    { ...loginResponse(), expires_in: '604800' }, { ...loginResponse(), token_type: 'Other' }]) {
    globalThis.fetch = async () => json(body);
    await assert.rejects(session.ensureSession(), /Invalid login response/);
    assert.equal(values.size, 0);
  }
});

test('SDK failure does not call the backend or persist a token', async () => {
  window.TTMinis.login = callback => callback({ error: { error_code: 102102 } });
  await assert.rejects(session.ensureSession(), /login failed/);
  assert.equal(values.size, 0);
});

test('storage restrictions still allow an in-memory session', async () => {
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() {
    throw new Error('Storage unavailable');
  } });
  globalThis.fetch = async () => json(loginResponse('test-session'));
  assert.equal(await session.ensureSession(), 'test-session');
  assert.equal(await session.ensureSession(), 'test-session');
  assert.equal(loginCalls, 1);
});

test('authenticated requests preserve Headers objects and do not expose error bodies', async () => {
  values.set('sailreels_session', 'test-session');
  globalThis.fetch = async (_url, init) => {
    assert.equal(init.method, 'POST');
    assert.equal(init.body, '{"value":1}');
    assert.equal(init.headers.get('X-Request-ID'), 'test-request');
    assert.equal(init.headers.get('Authorization'), 'Bearer test-session');
    assert.equal(init.headers.get('Content-Type'), 'application/json');
    return json({ detail: 'private-backend-diagnostic' }, 503);
  };
  await assert.rejects(session.apiFetch('/protected', {
    method: 'POST', body: '{"value":1}', headers: new Headers({ 'X-Request-ID': 'test-request' }),
  }), error => error.message.includes('503') && !error.message.includes('private-backend-diagnostic'));
  assert.equal(loginCalls, 0);
  assert.equal(values.get('sailreels_session'), 'test-session');
});

test('a missing SDK callback times out and a later user retry can succeed', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  window.TTMinis.login = () => {};
  const failed = assert.rejects(session.ensureSession(), /timed out/);
  t.mock.timers.tick(15_000);
  await failed;
  window.TTMinis.login = callback => callback({ authResponse: { code: 'new-test-code' } });
  globalThis.fetch = async () => json(loginResponse('test-session'));
  assert.equal(await session.ensureSession(), 'test-session');
});

test('a stalled login HTTP request is aborted instead of waiting forever', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const started = deferred();
  globalThis.fetch = async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    started.resolve();
  });
  const failed = assert.rejects(session.ensureSession(), { name: 'AbortError' });
  await started.promise;
  t.mock.timers.tick(20_000);
  await failed;
  assert.equal(values.size, 0);
});

test('an invalid /me response does not let startup report success', async () => {
  values.set('sailreels_session', 'test-session');
  globalThis.fetch = async () => json({});
  await assert.rejects(session.initializeSession(), /Invalid session response/);
});

test('the login deadline also covers a stalled response body and permits a fresh retry', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const readingBody = deferred();
  globalThis.fetch = async (_url, init) => ({
    ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      readingBody.resolve();
    }),
  });
  const failed = assert.rejects(session.ensureSession(), { name: 'AbortError' });
  await readingBody.promise;
  t.mock.timers.tick(20_000);
  await failed;
  assert.equal(values.size, 0);
  globalThis.fetch = async () => json(loginResponse());
  assert.equal(await session.ensureSession(), 'test-session');
  assert.equal(loginCalls, 2);
});

test('non-JSON upstream errors preserve status without retrying the session', async () => {
  values.set('sailreels_session', 'test-session');
  globalThis.fetch = async () => new Response('<html>private diagnostic</html>', { status: 502 });
  await assert.rejects(session.apiFetch('/auth/me'), { status: 502, detail: 'request_failed' });
  assert.equal(loginCalls, 0);
});

test('a 401 re-login to another account never replays the previous purchase or progress body', async () => {
  let logins = 0, writes = 0;
  globalThis.fetch = async url => {
    if (url.endsWith('/auth/login')) {
      logins++;
      return json({ ...loginResponse(`token-${logins}`), open_id: logins === 1 ? 'account-A' : 'account-B' });
    }
    writes++;
    return json({ detail: 'login_required' }, 401);
  };
  await session.ensureSession();
  await assert.rejects(session.apiFetch('/me/progress/1', { method: 'PUT', body: '{"seq":1,"position_seconds":42}' }),
    { status: 409, detail: 'session_changed' });
  assert.equal(logins, 2);
  assert.equal(writes, 1);
  assert.equal(session.getSessionOwner(), 'account-B');
});
