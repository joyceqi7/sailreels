/**
 * Session against our backend. TTMinis.login() -> code -> POST /auth/login -> our session token.
 * On 401 from any API call, the session is re-established once and the request retried.
 */
import { login } from './sdk';
import { API_BASE } from '../api/config';
import { APP_NAME } from '../app-identity';
import type { components } from '../../../../packages/api-types/schema';

// Per app: a token from one app's backend is meaningless to another's, so never share the slot.
const TOKEN_KEY = `${APP_NAME.toLowerCase()}_session`;
type LoginIn = components['schemas']['LoginIn'];
type LoginOut = components['schemas']['LoginOut'];
type ProfileOut = components['schemas']['ProfileOut'];
export type ProfileResponse = ProfileOut;

export class ApiRequestError extends Error {
  constructor(public readonly status: number, public readonly detail: string, public readonly orderId?: string) {
    super(`API request failed (${status}): ${detail}`);
  }
}

// Preserve v1 auth semantics without exposing arbitrary upstream diagnostics.
const AUTH_ERROR_DETAILS = new Set([
  'invalid_login_code', 'login_required', 'tiktok_unavailable',
  'auth_not_configured', 'tiktok_timeout',
  'subscription_order_pending', 'subscription_state_conflict', 'subscription_reactivation_blocked',
  'subscription_tier_unavailable', 'active_subscription_exists',
  'session_changed',
]);

function failure(response: { status: number; data: unknown }): ApiRequestError {
  const body = response.data;
  const detail = body && typeof body === 'object' && 'detail' in body
    && typeof body.detail === 'string' && AUTH_ERROR_DETAILS.has(body.detail)
    ? body.detail : 'request_failed';
  const orderId = body && typeof body === 'object' && 'order_id' in body && typeof body.order_id === 'string'
    && /^[a-zA-Z0-9_-]{1,64}$/.test(body.order_id) ? body.order_id : undefined;
  return new ApiRequestError(response.status, detail, orderId);
}

let pendingLogin: Promise<string> | null = null;
let memoryToken: string | null = null;
let sessionOpenId: string | null = null;
export const getSessionOwner = () => sessionOpenId;

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY) || memoryToken;
  } catch {
    return memoryToken;
  }
}

function saveToken(token: string | null): void {
  memoryToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Restricted storage must not prevent a session within this page lifetime.
  }
}

/** Bound network waits and preserve a caller's cancellation signal. */
async function sessionRequest(path: string, init: RequestInit, timeoutMs = 15_000): Promise<{
  ok: boolean; status: number; data: unknown;
}> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init.signal?.aborted) abort();
  else init.signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    // Keep the deadline active while reading the body, not only its headers.
    let data: unknown;
    try {
      data = await response.json();
    } catch (cause) {
      // Error proxies may return HTML. Preserve their status, but never hide
      // an abort or accept a malformed success response as valid data.
      if (response.ok || controller.signal.aborted) throw cause;
    }
    return { ok: response.ok, status: response.status, data };
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener('abort', abort);
  }
}

async function doLogin(): Promise<string> {
  const code = await login();
  const body: LoginIn = { code };
  const resp = await sessionRequest('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  }, 20_000);
  if (!resp.ok) throw failure(resp);
  const result = resp.data as Partial<LoginOut> | null;
  if (!result || typeof result.token !== 'string' || !result.token.trim()
    || typeof result.open_id !== 'string' || !result.open_id.trim()
    || typeof result.expires_in !== 'number' || !Number.isFinite(result.expires_in) || result.expires_in <= 0
    || (result.token_type !== undefined && result.token_type !== 'Bearer')) {
    throw new Error('Invalid login response.');
  }
  // Only our application's session is stored; never persist the one-time code.
  sessionOpenId = result.open_id;
  saveToken(result.token);
  return result.token;
}

/** Deduplicates concurrent logins: many 401s at once must not burn multiple codes. */
export function ensureSession(force = false, rejectedToken?: string): Promise<string> {
  if (pendingLogin) return pendingLogin;
  const cached = readToken();
  if (cached && (!force || (rejectedToken !== undefined && cached !== rejectedToken))) {
    return Promise.resolve(cached);
  }
  if (force) saveToken(null);
  pendingLogin = doLogin().finally(() => {
    pendingLogin = null;
  });
  return pendingLogin;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let owner = sessionOpenId;
  const call = (token: string) => {
    const headers = new Headers(init.headers);
    if (typeof init.body === 'string' && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    headers.set('Authorization', `Bearer ${token}`);
    return sessionRequest(path, {
      ...init,
      headers,
    });
  };
  let token = await ensureSession();
  owner ??= sessionOpenId;
  if (owner && owner !== sessionOpenId) throw new ApiRequestError(409, 'session_changed');
  let resp = await call(token);
  if (resp.status === 401) {
    // A delayed 401 for the old token must reuse a refresh already completed
    // by another request, rather than spend another one-time login code.
    token = await ensureSession(true, token);
    // Re-login may select another TikTok account. Never replay the old account's purchase/progress body.
    if (owner && owner !== sessionOpenId) throw new ApiRequestError(409, 'session_changed');
    resp = await call(token);
  }
  if (resp.status === 401 && readToken() === token) saveToken(null);
  // Do not surface raw backend bodies (which may contain OAuth diagnostics).
  if (!resp.ok) throw failure(resp);
  if (owner && owner !== sessionOpenId) throw new ApiRequestError(409, 'session_changed');
  return resp.data as T;
}

/** Validate a persisted session before displaying live application pages. */
export async function initializeSession(): Promise<void> {
  await getSessionProfile();
}

/** Preserve the shared helper used by other callers of the v1 session module. */
export async function getSessionProfile(): Promise<ProfileResponse> {
  const profile = await apiFetch<ProfileResponse>('/auth/me');
  if (!profile || typeof profile.open_id !== 'string' || !profile.open_id.trim()) {
    throw new Error('Invalid session response.');
  }
  sessionOpenId = profile.open_id;
  return profile;
}
