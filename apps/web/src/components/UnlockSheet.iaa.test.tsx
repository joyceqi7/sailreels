// @vitest-environment jsdom
/**
 * IAA-only builds (VITE_MONETIZATION=iaa): the rewarded ad is the only unlock. No Beans offers or VIP
 * link, and a locked episode the user opened directly can be unlocked with an ad right away.
 */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { UnlockSheet, type UnlockReason } from './UnlockSheet';
import { rememberPendingOrder } from '../api/monetization';
import { REWARDED_AD_CONFIGURED } from '../minis/ad-config';
import { apiFetch, ApiRequestError } from '../minis/session';

vi.mock('../api/config', () => ({ MOCK_API_ENABLED: false, API_BASE: '/api/v1' }));
vi.mock('../monetization', () => ({ IAP_ENABLED: false }));
vi.mock('../minis/ad-config', () => ({
  AD_UNIT_IDS: { rewarded: 'ad_test_unit', interstitial: '' }, REWARDED_AD_CONFIGURED: true,
}));
vi.mock('../minis/session', async importOriginal => ({
  ...await importOriginal<typeof import('../minis/session')>(), apiFetch: vi.fn(),
}));
const api = vi.mocked(apiFetch);
const unlocked = vi.fn();
let closeAd: (result: { isEnded?: boolean }) => void;
let claim: () => Promise<unknown>;

beforeEach(() => {
  unlocked.mockReset().mockResolvedValue(undefined); rememberPendingOrder('1', 2);
  claim = async () => ({ ok: true });
  Object.defineProperty(window, 'TTMinis', { configurable: true, value: {
    canIUse: () => true,
    createRewardedVideoAd: vi.fn(() => ({ show: vi.fn().mockResolvedValue(undefined),
      onClose: (cb: typeof closeAd) => { closeAd = cb; }, offClose: vi.fn(), onError: vi.fn(), offError: vi.fn() })),
  } });
  api.mockReset().mockImplementation(async path => {
    if (path.endsWith('/unlock-options')) return { drama_id: 1, seq: 2, rewarded_ad: true, offers: [] };
    if (path.endsWith('/nonce')) return { nonce: 'n1' };
    if (path.endsWith('/claim')) return claim();
    if (path.endsWith('/access')) return { access: 'unlocked', episode: { seq: 2, title: 'EP2', locked: false,
      album_id: '7667061213232384021', episode_id: '7667063938195032072', vid: 'v2' } };
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); delete (window as Window & { TTMinis?: unknown }).TTMinis; });

function sheet(reason: UnlockReason = 'jump') {
  return render(<MemoryRouter>
    <UnlockSheet dramaId="1" seq={2} reason={reason} onClose={vi.fn()} onUnlocked={unlocked} />
  </MemoryRouter>);
}

it('offers only the rewarded ad: no Beans, no VIP', async () => {
  sheet();
  await screen.findByRole('button', { name: 'Watch an ad · unlock this episode' });
  expect(screen.queryByText(/Beans/)).toBeNull();
  expect(screen.queryByRole('link', { name: /VIP/ })).toBeNull();
});

it('a directly opened locked episode unlocks with a completed ad', async () => {
  const user = userEvent.setup(); sheet('entry');
  const watch = await screen.findByRole('button', { name: 'Watch an ad · unlock this episode' });
  expect(watch.hasAttribute('disabled')).toBe(false);
  expect(screen.queryByText(/Watch a free episode first/)).toBeNull();
  await user.click(watch);
  await act(async () => closeAd({ isEnded: true }));
  await waitFor(() => expect(unlocked).toHaveBeenCalledTimes(1));
  expect(api.mock.calls.filter(([path]) => path.endsWith('/claim'))).toHaveLength(1);
});

it('the daily-limit message does not point to Beans', async () => {
  claim = async () => { throw new ApiRequestError(429, 'ad_daily_limit'); };
  const user = userEvent.setup(); sheet();
  await user.click(await screen.findByRole('button', { name: 'Watch an ad · unlock this episode' }));
  await act(async () => closeAd({ isEnded: true }));
  expect(await screen.findByText('Your ad reward limit has been reached. Try again later.')).toBeTruthy();
});

it('says unlocking is unavailable when there is no ad to offer', async () => {
  vi.spyOn(await import('../minis/ad-config'), 'REWARDED_AD_CONFIGURED', 'get').mockReturnValue(false);
  expect(REWARDED_AD_CONFIGURED).toBe(false);
  sheet();
  expect(await screen.findByText(/Unlocking is not available right now/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Watch an ad · unlock this episode' })).toBeNull();
});
