import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ api: vi.fn(), pay: vi.fn(), ad: vi.fn(), supports: vi.fn() }));
vi.mock('./session', () => ({ apiFetch: mocks.api }));
vi.mock('./sdk', () => ({ pay: mocks.pay, showRewardedAd: mocks.ad,
  supportsRewardedAd: mocks.supports, subscribe: vi.fn() }));

import { AD_UNIT_IDS } from './ad-config';
import { pollBeansOrder, unlockWithAd, unlockWithBeans } from './unlock';

const access = { access: 'unlocked', episode: { seq: 2, locked: false, vid: 'v2', episode_id: 'e2' } };

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  mocks.supports.mockReturnValue(true);
  mocks.pay.mockResolvedValue(undefined);
  mocks.ad.mockResolvedValue(true);
});
afterEach(() => vi.useRealTimers());

it('creates one order, waits after the pay callback, and verifies authoritative access', async () => {
  mocks.api.mockResolvedValueOnce({ order_id: 'b1', trade_order_id: 'T1' })
    .mockResolvedValueOnce({ status: 'created' }).mockResolvedValueOnce({ status: 'paid' })
    .mockResolvedValueOnce(access);
  const result = unlockWithBeans(1, 2);
  await vi.advanceTimersByTimeAsync(1500);
  expect(await result).toBe(true);
  expect(mocks.pay).toHaveBeenCalledExactlyOnceWith('T1');
  expect(mocks.api.mock.calls.map(([path]) => path)).toEqual([
    '/orders/beans', '/orders/beans/b1', '/orders/beans/b1', '/dramas/1/episodes/2/access',
  ]);
  expect(JSON.parse(mocks.api.mock.calls[0][1].body)).toEqual({ drama_id: 1, seq: 2 });
});

it('does not report paid sandbox orders as unlocked when the backend denies access', async () => {
  mocks.api.mockResolvedValueOnce({ order_id: 'b1', trade_order_id: 'T1' })
    .mockResolvedValueOnce({ status: 'paid' }).mockResolvedValueOnce({ access: 'locked', episode: null });
  expect(await unlockWithBeans(1, 2)).toBe(false);
});

it.each(['refunded', 'failed'])('stops polling a %s order immediately', async status => {
  mocks.api.mockResolvedValueOnce({ order_id: 'b1', trade_order_id: 'T1' })
    .mockResolvedValueOnce({ status });
  expect(await unlockWithBeans(1, 2)).toBe(false);
  expect(mocks.api).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
});

it('times out without a second order and can resume polling a known order', async () => {
  mocks.api.mockResolvedValue({ status: 'created' });
  const result = pollBeansOrder('b1', 2000);
  await vi.advanceTimersByTimeAsync(2000);
  expect(await result).toBe('created');
  expect(mocks.api.mock.calls.every(([path]) => path === '/orders/beans/b1')).toBe(true);
  mocks.api.mockResolvedValueOnce({ status: 'paid' });
  expect(await pollBeansOrder('b1')).toBe('paid');
  expect(mocks.pay).not.toHaveBeenCalled();
});

it('does not replay order creation or show the panel after a backend failure', async () => {
  mocks.api.mockRejectedValueOnce(new Error('tiktok_timeout'));
  await expect(unlockWithBeans(1, 2)).rejects.toThrow('tiktok_timeout');
  expect(mocks.api).toHaveBeenCalledTimes(1);
  expect(mocks.pay).not.toHaveBeenCalled();
});

it('checks support before requesting a nonce', async () => {
  mocks.supports.mockReturnValue(false);
  await expect(unlockWithAd(1, 2)).rejects.toThrow('rewarded_ad_unsupported');
  expect(mocks.api).not.toHaveBeenCalled();
});

it.each([false, undefined])('never claims when the ad completion result is %s', async ended => {
  mocks.api.mockResolvedValueOnce({ nonce: 'n1' });
  mocks.ad.mockResolvedValueOnce(ended);
  expect(await unlockWithAd(1, 2)).toBe(false);
  expect(mocks.api).toHaveBeenCalledTimes(1);
});

it('claims only the issued nonce after completion and then rechecks episode access', async () => {
  mocks.api.mockResolvedValueOnce({ nonce: 'n1' }).mockResolvedValueOnce({ ok: true })
    .mockResolvedValueOnce(access);
  expect(await unlockWithAd(1, 2)).toBe(true);
  expect(mocks.ad).toHaveBeenCalledExactlyOnceWith(AD_UNIT_IDS.rewarded);
  expect(mocks.api.mock.calls.map(([path]) => path)).toEqual([
    '/ads/rewarded/nonce', '/ads/rewarded/claim', '/dramas/1/episodes/2/access',
  ]);
  expect(JSON.parse(mocks.api.mock.calls[1][1].body)).toEqual({ nonce: 'n1' });
});

it('does not claim after an ad error, or auto-replay a failed claim', async () => {
  mocks.api.mockResolvedValueOnce({ nonce: 'n1' });
  mocks.ad.mockRejectedValueOnce(new Error('ad failed'));
  await expect(unlockWithAd(1, 2)).rejects.toThrow('ad failed');
  expect(mocks.api).toHaveBeenCalledTimes(1);
  mocks.api.mockResolvedValueOnce({ nonce: 'n2' }).mockRejectedValueOnce(new Error('nonce_expired'));
  await expect(unlockWithAd(1, 2)).rejects.toThrow('nonce_expired');
  expect(mocks.api).toHaveBeenCalledTimes(3);
});
