import { afterEach, expect, it, vi } from 'vitest';
import { hideSubscriptionRibbon, login, pay, showRewardedAd, showSurfaceCoupon, subscribe } from './sdk';

// The app's default ad unit is empty until SailReels activates one, so these tests pass an ID
// explicitly and exercise the ad mechanics rather than the app's ad configuration.
const AD = 'ad_test_unit';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('subscription callbacks do not prove benefits and a missing callback is bounded', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('window', { TTMinis: { createSubscription: (cb: (r: object) => void) => cb({ is_success: true }),
    reactivateSubscription: vi.fn() } });
  await expect(subscribe('T1')).resolves.toBeUndefined();
  const result = expect(subscribe('T2', true)).rejects.toThrow('Subscription panel timed out');
  await vi.advanceTimersByTimeAsync(120_000); await result;
  expect(vi.getTimerCount()).toBe(0);
});
it('coupon calls degrade to empty discounts, time out, and clean up the ribbon', async () => {
  vi.useFakeTimers();
  const hide = vi.fn();
  vi.stubGlobal('window', { TTMinis: { canIUse: () => true, hideRibbon: hide, showSurfaceCoupon: vi.fn() } });
  const result = showSurfaceCoupon(); await vi.advanceTimersByTimeAsync(5000);
  expect(await result).toBe(''); hideSubscriptionRibbon(); expect(hide).toHaveBeenCalledTimes(1);
});

it('times out when the Minis login callback never arrives', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('window', { TTMinis: { login: vi.fn() } });
  const result = expect(login()).rejects.toThrow('TikTok login timed out');
  await vi.advanceTimersByTimeAsync(15_000);
  await result;
});

it('returns the one-time code and cleans up the callback timeout', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('window', { TTMinis: {
    login: (callback: (result: { authResponse: { code: string } }) => void) =>
      callback({ authResponse: { code: 'code' } }),
  } });
  expect(await login()).toBe('code');
  expect(vi.getTimerCount()).toBe(0);
});

it('rejects SDK failures without leaving a timer running', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('window', { TTMinis: { login: () => { throw new Error('SDK failure'); } } });
  await expect(login()).rejects.toThrow('SDK failure');
  expect(vi.getTimerCount()).toBe(0);
});

it('does not interpret a payment callback as proof of fulfillment', async () => {
  vi.useFakeTimers();
  const payment = vi.fn((callback: (r: object) => void) => callback({ is_success: false }));
  vi.stubGlobal('window', { TTMinis: { pay: payment } });
  await expect(pay('T1')).resolves.toBeUndefined();
  expect(payment.mock.calls[0][0]).toBeTypeOf('function');
  expect(vi.getTimerCount()).toBe(0);
});

it('bounds a missing payment callback and cleans up a synchronous SDK failure', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('window', { TTMinis: { pay: vi.fn() } });
  const result = expect(pay('T1')).rejects.toThrow('Payment panel timed out');
  await vi.advanceTimersByTimeAsync(120_000);
  await result;
  vi.stubGlobal('window', { TTMinis: { pay: () => { throw new Error('SDK failed'); } } });
  await expect(pay('T2')).rejects.toThrow('SDK failed');
  expect(vi.getTimerCount()).toBe(0);
});

it.each([true, false, undefined])('requires isEnded === true, got %s', async ended => {
  let onClose: (res: { isEnded?: boolean }) => void;
  const ad = { show: vi.fn().mockResolvedValue(undefined),
    onClose: vi.fn(cb => { onClose = cb; }), offClose: vi.fn(), onError: vi.fn(), offError: vi.fn() };
  const create = vi.fn(() => ad);
  vi.stubGlobal('window', { TTMinis: { createRewardedVideoAd: create } });
  const result = showRewardedAd(AD);
  onClose!({ isEnded: ended });
  expect(await result).toBe(ended === true);
  expect(ad.offClose).toHaveBeenCalledTimes(1);
  expect(ad.offError).toHaveBeenCalledTimes(1);
  const next = showRewardedAd(AD);
  onClose!({ isEnded: true });
  await next;
  expect(create).toHaveBeenCalledTimes(2);
});

it('removes ad callbacks when show throws synchronously', async () => {
  const ad = { show: () => { throw new Error('show failed'); },
    onClose: vi.fn(), offClose: vi.fn(), onError: vi.fn(), offError: vi.fn() };
  vi.stubGlobal('window', { TTMinis: { createRewardedVideoAd: () => ad } });
  await expect(showRewardedAd(AD)).rejects.toThrow('rewardedVideoAd failed');
  expect(ad.offClose).toHaveBeenCalledTimes(1);
  expect(ad.offError).toHaveBeenCalledTimes(1);
});
