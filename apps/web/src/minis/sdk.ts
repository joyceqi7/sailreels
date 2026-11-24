/**
 * Typed wrapper over window.TTMinis client capabilities (login, pay, subscription, ads, events).
 * The player is handled separately in plugins/minis-player.
 *
 * Docs: docs/official/20-login.md, 30-iap-beans.md, 31-subscription.md, 40-iaa-rewarded-ad.md, 41-event-postback.md
 * Every callback-style JSAPI is promisified here; nothing else in the app should touch window.TTMinis.
 */

import { AD_UNIT_IDS } from './ad-config';

interface MinisError {
  error_code?: number | string;
  errorCode?: number | string;
  error_msg?: string;
  message?: string;
}

interface RewardedVideoAd {
  show(): Promise<void>;
  onClose(cb: (res: { isEnded?: boolean }) => void): void;
  offClose(cb: (res: { isEnded?: boolean }) => void): void;
  onError(cb: (err: unknown) => void): void;
  offError(cb: (err: unknown) => void): void;
}

interface TTMinisApi {
  isMinisRuntime?: boolean;
  canIUse(schema: string): boolean;
  login(cb: (res: { authResponse?: { code: string }; error?: MinisError }) => void): void;
  authorize(
    cb: (res: { authResponse?: { code: string; grantedScopes?: string }; error?: MinisError }) => void,
    opts: { scope: string; returnScopes: boolean },
  ): void;
  pay(
    cb: (res: { is_success?: boolean; trade_order_id?: string; error?: MinisError }) => void,
    opts: { trade_order_id: string; log_extra?: Record<string, unknown> },
  ): void;
  createSubscription(
    cb: (res: { is_success?: boolean; trade_order_id?: string; error?: MinisError }) => void,
    opts: { trade_order_id: string },
  ): void;
  reactivateSubscription(
    cb: (res: { is_success?: boolean; trade_order_id?: string; error?: MinisError }) => void,
    opts: { trade_order_id: string },
  ): void;
  showSurfaceCoupon?(cb: (res: { is_success: boolean; coupon_discount?: string }) => void): void;
  hideRibbon?(cb: (res: { is_success: boolean }) => void): void;
  createRewardedVideoAd(opts: { adUnitId: string }): RewardedVideoAd;
  reportEvent(opts: {
    eventName: string;
    params: Record<string, string | number | null>;
    callback?: (result: { isSuccess: boolean; error?: unknown }) => void;
  }): void;
}

export class MinisCallError extends Error {
  constructor(public readonly api: string, public readonly detail: MinisError | unknown) {
    super(`${api} failed: ${JSON.stringify(detail)}`);
  }
}

function sdk(): TTMinisApi {
  const minis = (window as Window & { TTMinis?: TTMinisApi }).TTMinis;
  if (!minis) throw new Error('TikTok Minis SDK is not loaded.');
  return minis;
}

export function canIUse(schema: string): boolean {
  try {
    return sdk().canIUse(schema);
  } catch {
    return false;
  }
}

/** One-time code, valid ~5 minutes. Send it to the backend immediately; never cache it. */
export function login(): Promise<string> {
  return new Promise((resolve, reject) => {
    const minis = sdk();
    const timer = setTimeout(() => reject(new Error('TikTok login timed out. Please try again.')), 15_000);
    try {
      minis.login((res) => {
        clearTimeout(timer);
        if (res.error || !res.authResponse?.code) reject(new MinisCallError('login', res.error));
        else resolve(res.authResponse.code);
      });
    } catch (error) {
      clearTimeout(timer);
      reject(error);
    }
  });
}

/** Only call from an explicit user action (profile page), never on page load. */
export function authorizeProfile(): Promise<void> {
  return new Promise((resolve, reject) => {
    sdk().authorize(
      (res) => (res.error ? reject(new MinisCallError('authorize', res.error)) : resolve()),
      { scope: 'user.info.basic', returnScopes: true },
    );
  });
}

/** Resolves when the pay panel closes. This is NOT proof of payment — poll the backend order status. */
export function pay(tradeOrderId: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Payment panel timed out. Check your order before retrying.')),
      120_000);
    try {
      sdk().pay(
        (res) => {
          clearTimeout(timer);
          if (res.error) reject(new MinisCallError('pay', res.error));
          else resolve();
        },
        { trade_order_id: tradeOrderId },
      );
    } catch (error) {
      clearTimeout(timer);
      reject(error);
    }
  });
}

/** Same caveat as pay(): final state comes from the backend (webhook). */
export function subscribe(tradeOrderId: string, reactivate = false): Promise<void> {
  const api = reactivate ? 'reactivateSubscription' : 'createSubscription';
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Subscription panel timed out. Check your existing order.')), 120_000);
    try {
      sdk()[api](res => {
        clearTimeout(timer);
        if (res.error) reject(new MinisCallError(api, res.error));
        else resolve(); // Even is_success=true requires a confirmed server order.
      }, { trade_order_id: tradeOrderId });
    } catch (error) { clearTimeout(timer); reject(error); }
  });
}

/** An empty discount is normal on unsupported versions or when no coupon has been assigned. */
export function showSurfaceCoupon(): Promise<string> {
  if (!canIUse('showSurfaceCoupon')) return Promise.resolve('');
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(''), 5000);
    try {
      sdk().showSurfaceCoupon?.(res => {
        clearTimeout(timer);
        resolve(res.is_success && typeof res.coupon_discount === 'string' ? res.coupon_discount : '');
      });
    } catch { clearTimeout(timer); resolve(''); }
  });
}

export function hideSubscriptionRibbon(): void {
  if (!canIUse('hideRibbon')) return;
  try { sdk().hideRibbon?.(() => undefined); } catch { /* Page navigation must still finish. */ }
}

/**
 * Rewarded ad. Resolves true only when the user watched to the end (isEnded === true).
 * A fresh instance per show, as recommended. Caller must check supportsRewardedAd() first.
 * An empty adUnitId means this app has no activated ad unit; fail loudly here rather than calling
 * createRewardedVideoAd('') and surfacing an opaque SDK error after the user has already tapped.
 */
export function showRewardedAd(adUnitId: string = AD_UNIT_IDS.rewarded): Promise<boolean> {
  if (!adUnitId) return Promise.reject(new Error('rewarded_ad_not_configured'));
  return new Promise((resolve, reject) => {
    const ad = sdk().createRewardedVideoAd({ adUnitId });
    let settled = false;
    const onClose = (res: { isEnded?: boolean }) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(res.isEnded === true);
    };
    const onError = (err: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new MinisCallError('rewardedVideoAd', err));
    };
    const cleanup = () => {
      ad.offClose(onClose);
      ad.offError(onError);
    };
    ad.onClose(onClose);
    ad.onError(onError);
    try {
      ad.show().catch(onError);
    } catch (error) {
      onError(error);
    }
  });
}

/** IAA needs TikTok >= 44.2.0; show an "update TikTok" prompt when false. */
export function supportsRewardedAd(): boolean {
  return canIUse('createRewardedVideoAd');
}

/** Middle-funnel event postback. Fire-and-forget; never block UX on it. Needs TikTok >= 40.9.0. */
export function reportEvent(eventName: string, params: Record<string, string | number | null>): void {
  if (!canIUse('reportEvent')) return;
  try {
    sdk().reportEvent({
      eventName,
      params,
      callback: (r) => {
        if (!r.isSuccess && import.meta.env.DEV) console.warn('[reportEvent]', eventName, r.error);
      },
    });
  } catch (e) {
    if (import.meta.env.DEV) console.warn('[reportEvent]', eventName, e);
  }
}
