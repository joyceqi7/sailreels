// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { UnlockSheet } from './UnlockSheet';
import { rememberPendingOrder } from '../api/monetization';
import { apiFetch, ApiRequestError } from '../minis/session';

vi.mock('../api/config', () => ({ MOCK_API_ENABLED: false, API_BASE: '/api/v1' }));
// These tests cover the unlock UI, so they assume this app HAS an activated rewarded ad unit.
// The unconfigured case (SailReels before activation) is covered by UnlockSheet.noads.test.tsx.
vi.mock('../minis/ad-config', () => ({
  AD_UNIT_IDS: { rewarded: 'ad_test_unit', interstitial: '' }, REWARDED_AD_CONFIGURED: true,
}));
vi.mock('../minis/session', async importOriginal => ({
  ...await importOriginal<typeof import('../minis/session')>(), apiFetch: vi.fn(),
}));
const api = vi.mocked(apiFetch);
let supported: boolean;
let completePayment: (result: { is_success?: boolean }) => void;
let closeAd: (result: { isEnded?: boolean }) => void;
let showPayment: ReturnType<typeof vi.fn>;
let createAd: ReturnType<typeof vi.fn>;
const unlocked = vi.fn();
const access = { access: 'unlocked', episode: { seq: 2, title: 'EP2', locked: false,
  album_id: '7667061213232384021', episode_id: '7667063938195032072', vid: 'v2' } };

beforeEach(() => {
  supported = true; unlocked.mockReset().mockResolvedValue(undefined); api.mockReset();
  rememberPendingOrder('1', 2);
  showPayment = vi.fn(cb => { completePayment = cb; });
  createAd = vi.fn(() => ({ show: vi.fn().mockResolvedValue(undefined),
    onClose: (cb: typeof closeAd) => { closeAd = cb; }, offClose: vi.fn(), onError: vi.fn(), offError: vi.fn() }));
  Object.defineProperty(window, 'TTMinis', { configurable: true, value: {
    canIUse: () => supported, pay: showPayment, createRewardedVideoAd: createAd,
  } });
  api.mockImplementation(async path => {
    if (path.endsWith('/unlock-options')) return { drama_id: 1, seq: 2, rewarded_ad: true,
      offers: [1, 3, 10].map(quantity => ({ quantity, token_amount: 100 * quantity, available: true,
        episode_seqs: Array.from({ length: quantity }, (_, index) => index + 2) })) };
    if (path === '/orders/beans') return { order_id: 'b1', trade_order_id: 'T1' };
    if (path === '/orders/beans/b1') return { order_id: 'b1', status: 'paid' };
    if (path.endsWith('/access')) return access;
    if (path.endsWith('/nonce')) return { nonce: 'n1' };
    if (path.endsWith('/claim')) return { ok: true };
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); delete (window as Window & { TTMinis?: unknown }).TTMinis; });

function sheet() { return render(<MemoryRouter><UnlockSheet dramaId="1" seq={2} reason="jump" onClose={vi.fn()} onUnlocked={unlocked} /></MemoryRouter>); }

it('unsupported clients see an upgrade prompt and never request an ad nonce', async () => {
  supported = false; sheet();
  await screen.findByRole('button', { name: /Single episode/ });
  expect(screen.getByText(/Update TikTok to watch rewarded ads/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Watch an ad · unlock this episode' }).hasAttribute('disabled')).toBe(true);
  expect(api.mock.calls.some(([path]) => path.endsWith('/nonce'))).toBe(false);
});

it.each([3, 10])('sends the server %i-episode offer price and waits for callback plus paid/access confirmation', async quantity => {
  const user = userEvent.setup(); sheet();
  await user.click(await screen.findByRole('button', { name: new RegExp(`${quantity} episodes.*${quantity * 100} Beans`) }));
  const request = api.mock.calls.find(([path]) => path === '/orders/beans')!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({ drama_id: 1, seq: 2, quantity, expected_token_amount: quantity * 100 });
  expect(showPayment).toHaveBeenCalledTimes(1); expect(unlocked).not.toHaveBeenCalled();
  await act(async () => completePayment({ is_success: true }));
  await waitFor(() => expect(unlocked).toHaveBeenCalledTimes(1));
  expect(api.mock.calls.some(([path]) => path.endsWith('/access'))).toBe(true);
});

it('a paid order without access stays available to check and cannot start a second purchase', async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation(async (path, init) => path.endsWith('/access')
    ? { access: 'locked', episode: null } : original(path, init));
  const user = userEvent.setup(); sheet();
  await user.click(await screen.findByRole('button', { name: /Single episode.*100 Beans/ }));
  await act(async () => completePayment({ is_success: true }));
  await screen.findByText(/Payment confirmed. Viewing access is not ready/);
  expect(unlocked).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: /Single episode.*100 Beans/ }).hasAttribute('disabled')).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Check existing order' }));
  expect(showPayment).toHaveBeenCalledTimes(1);
});

it('SDK ad show does not grant; only the complete close callback can claim', async () => {
  const user = userEvent.setup(); sheet();
  await user.click(await screen.findByRole('button', { name: 'Watch an ad · unlock this episode' }));
  expect(createAd).toHaveBeenCalledTimes(1);
  expect(api.mock.calls.some(([path]) => path.endsWith('/claim'))).toBe(false);
  await act(async () => closeAd({ isEnded: false }));
  expect(api.mock.calls.some(([path]) => path.endsWith('/claim'))).toBe(false);
  await user.click(screen.getByRole('button', { name: 'Watch an ad · unlock this episode' }));
  await act(async () => closeAd({ isEnded: true }));
  await waitFor(() => expect(unlocked).toHaveBeenCalledTimes(1));
  expect(api.mock.calls.filter(([path]) => path.endsWith('/claim'))).toHaveLength(1);
  expect(createAd).toHaveBeenCalledTimes(2);
});

it('rapid double clicks cannot create two orders while the payment callback is pending', async () => {
  sheet(); const button = await screen.findByRole('button', { name: /Single episode.*100 Beans/ });
  fireEvent.click(button); fireEvent.click(button);
  await waitFor(() => expect(showPayment).toHaveBeenCalledTimes(1));
  expect(api.mock.calls.filter(([path]) => path === '/orders/beans')).toHaveLength(1);
  await act(async () => completePayment({ is_success: false }));
});

it('a server timeout keeps the returned business order ID instead of retrying payment', async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation(async (path, init) => {
    if (path === '/orders/beans') throw new ApiRequestError(504, 'tiktok_timeout', 'b_uncertain');
    if (path === '/orders/beans/b_uncertain') return { status: 'created', order_id: 'b_uncertain' };
    return original(path, init);
  });
  const user = userEvent.setup(); sheet();
  await user.click(await screen.findByRole('button', { name: /Single episode.*100 Beans/ }));
  await screen.findByText(/Order confirmation was delayed/);
  expect(screen.getByText('Order: b_uncertain')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Check existing order' }));
  expect(api.mock.calls.filter(([path]) => path === '/orders/beans')).toHaveLength(1);
  expect(showPayment).not.toHaveBeenCalled();
});

it('a concurrent grant reported as 409 refreshes access instead of charging again', async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation(async (path, init) => {
    if (path === '/orders/beans') throw new ApiRequestError(409, 'request_failed');
    return original(path, init);
  });
  const user = userEvent.setup(); sheet();
  await user.click(await screen.findByRole('button', { name: /Single episode.*100 Beans/ }));
  await waitFor(() => expect(unlocked).toHaveBeenCalledTimes(1));
  expect(showPayment).not.toHaveBeenCalled();
});
