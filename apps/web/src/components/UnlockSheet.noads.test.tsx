// @vitest-environment jsdom
/**
 * When an app has no activated rewarded ad unit, the unlock sheet must not offer an ad at all:
 * showing a disabled button would advertise a reward the app can never deliver, and
 * showRewardedAd('') fails only after the user has tapped. SailReels ships WITH a rewarded unit,
 * so this unconfigured case is forced via a mock rather than relying on the default config.
 */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { UnlockSheet } from './UnlockSheet';
import { rememberPendingOrder } from '../api/monetization';
import { apiFetch } from '../minis/session';

vi.mock('../api/config', () => ({ MOCK_API_ENABLED: false, API_BASE: '/api/v1' }));
// Force the "no ad unit" branch regardless of the app's real (configured) default.
vi.mock('../minis/ad-config', () => ({
  AD_UNIT_IDS: { rewarded: '', interstitial: '' }, REWARDED_AD_CONFIGURED: false,
}));
vi.mock('../minis/session', async importOriginal => ({
  ...await importOriginal<typeof import('../minis/session')>(), apiFetch: vi.fn(),
}));
const api = vi.mocked(apiFetch);

beforeEach(() => {
  rememberPendingOrder('1', 2);
  api.mockReset().mockImplementation(async path => {
    if (path.endsWith('/unlock-options')) return { drama_id: 1, seq: 2, rewarded_ad: true,
      offers: [1, 3, 10].map(quantity => ({ quantity, token_amount: 100 * quantity, available: true,
        episode_seqs: Array.from({ length: quantity }, (_, index) => index + 2) })) };
    throw new Error(`Unexpected request ${path}`);
  });
  Object.defineProperty(window, 'TTMinis', { configurable: true, value: {
    canIUse: () => true, createRewardedVideoAd: vi.fn(),
  } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); delete (window as Window & { TTMinis?: unknown }).TTMinis; });

function sheet() {
  return render(<MemoryRouter>
    <UnlockSheet dramaId="1" seq={2} reason="jump" onClose={vi.fn()} onUnlocked={vi.fn()} />
  </MemoryRouter>);
}

it('offers Beans but never a rewarded ad when no ad unit is configured', async () => {
  sheet();
  // Beans purchasing still works, so the sheet itself is functional.
  await screen.findByRole('button', { name: /Single episode.*100 Beans/ });
  expect(screen.queryByRole('button', { name: 'Watch an ad · unlock this episode' })).toBeNull();
  // The upgrade hint belongs to a different failure (old client); it must not appear either.
  expect(screen.queryByText(/Update TikTok to watch rewarded ads/)).toBeNull();
});
