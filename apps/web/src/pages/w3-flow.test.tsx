// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SubscriptionPage } from './SubscriptionPage';
import { HistoryPage, ProfilePage, WalletPage } from './AccountPages';
import * as subscriptions from '../api/subscriptions';
import * as account from '../api/account';
import * as sdk from '../minis/sdk';

vi.mock('../hooks/useDramaApi', () => ({ useDramaList: () => ({ data: [], loading: false }) }));
vi.mock('../api/config', () => ({ MOCK_API_ENABLED: false, API_BASE: '/api/v1' }));
vi.mock('../api/subscriptions', () => ({ getSubscription: vi.fn(), getPlatformSubscriptions: vi.fn(),
  getSubscriptionTiers: vi.fn(), createSubscriptionOrder: vi.fn(), getSubscriptionOrder: vi.fn(),
  pollSubscriptionOrder: vi.fn(), querySubscriptionOrder: vi.fn(), completePreviewSubscription: vi.fn(),
  previewSubscriptionState: vi.fn() }));
vi.mock('../api/account', () => ({ getHistory: vi.fn(), getWallet: vi.fn(), getProfile: vi.fn(), connectProfile: vi.fn() }));
vi.mock('../minis/sdk', () => ({ canIUse: vi.fn(), subscribe: vi.fn(), showSurfaceCoupon: vi.fn(), hideSubscriptionRibbon: vi.fn() }));
const order = { order_id: 's1', trade_order_id: 'T1', status: 'created' as const, kind: 'create' as const, subscription_id: null };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(subscriptions.getSubscription).mockResolvedValue({ is_sandbox: true, renewal_normal: false, active: false, state: 'none' });
  vi.mocked(subscriptions.getPlatformSubscriptions).mockResolvedValue([]);
  vi.mocked(subscriptions.getSubscriptionTiers).mockResolvedValue([
    { tier_id: 't1', price: '4.99', currency: 'USD', deduct_cycle: 'MONTHLY', is_sandbox: false }]);
  vi.mocked(subscriptions.createSubscriptionOrder).mockResolvedValue({ order_id: 's1', trade_order_id: 'T1' });
  vi.mocked(subscriptions.getSubscriptionOrder).mockResolvedValue(order);
  vi.mocked(subscriptions.pollSubscriptionOrder).mockResolvedValue(order);
  vi.mocked(subscriptions.querySubscriptionOrder).mockResolvedValue({ order, platform_status: 'SUCCESS', awaiting_webhook: true });
  vi.mocked(sdk.canIUse).mockReturnValue(true);
  vi.mocked(sdk.subscribe).mockResolvedValue(undefined);
  vi.mocked(sdk.showSurfaceCoupon).mockResolvedValue('20% OFF');
  vi.mocked(account.getProfile).mockResolvedValue({ open_id: 'u1', nickname: null, avatar_url: null });
  vi.mocked(account.connectProfile).mockResolvedValue({ open_id: 'u1', nickname: 'Joyce', avatar_url: null });
});
afterEach(() => cleanup());
const view = (page: React.ReactNode) => render(<MemoryRouter>{page}</MemoryRouter>);

it('shows only actual SDK coupon text and hides the platform ribbon on leaving', async () => {
  const result = view(<SubscriptionPage />);
  expect(await screen.findByText('TikTok offer: 20% OFF')).toBeTruthy();
  result.unmount(); expect(sdk.hideSubscriptionRibbon).toHaveBeenCalled();
});
it('does not invent a coupon when the SDK returns no discount', async () => {
  vi.mocked(sdk.showSurfaceCoupon).mockResolvedValue(''); view(<SubscriptionPage />);
  await screen.findByRole('button', { name: /monthly.*USD 4.99/i });
  expect(screen.queryByText(/TikTok offer/)).toBeNull();
});
it('a successful panel and SUCCESS query never activate VIP without the webhook', async () => {
  const user = userEvent.setup(); view(<SubscriptionPage />);
  await user.click(await screen.findByRole('button', { name: /monthly.*USD 4.99/i }));
  expect(await screen.findByText(/Payment received by TikTok/)).toBeTruthy();
  expect(screen.queryByText('VIP is active')).toBeNull();
  expect(screen.queryByRole('button', { name: /monthly.*USD 4.99/i })).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Check existing order' }));
  expect(subscriptions.createSubscriptionOrder).toHaveBeenCalledTimes(1);
  expect(sdk.subscribe).toHaveBeenCalledWith('T1', false);
});
it('cancel keeps benefits and offers reactivate instead of another purchase', async () => {
  vi.mocked(subscriptions.getSubscription).mockResolvedValue({ is_sandbox: true, renewal_normal: false, active: true, state: 'cancel', subscription_id: 'S' });
  vi.mocked(subscriptions.getPlatformSubscriptions).mockResolvedValue([{ subscription_id: 'S', tier_id: 't1',
    state: 'cancel', rights_valid: true, renewal_normal: false, is_sandbox: true, end_time: null }]);
  const user = userEvent.setup(); view(<SubscriptionPage />);
  await user.click(await screen.findByRole('button', { name: 'Reactivate subscription' }));
  await waitFor(() => expect(sdk.subscribe).toHaveBeenCalledWith('T1', true));
  expect(subscriptions.createSubscriptionOrder).toHaveBeenCalledWith('', 'S');
  expect(screen.queryByRole('button', { name: /monthly/i })).toBeNull();
});
it('OnHold guides to store and may retain benefits but blocks both purchase actions', async () => {
  vi.mocked(subscriptions.getSubscription).mockResolvedValue({ is_sandbox: true, renewal_normal: false, active: true, state: 'onhold', subscription_id: 'S' });
  view(<SubscriptionPage />);
  expect(await screen.findByText('Payment needs attention')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Google Play subscriptions' }).getAttribute('href')).toContain('play.google.com');
  expect(screen.getByText('Your current benefits are still available.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Reactivate subscription' })).toBeNull();
  expect(screen.queryByRole('button', { name: /monthly/i })).toBeNull();
});
it('restores an existing order after reload and never creates a second one', async () => {
  vi.mocked(subscriptions.getSubscription).mockResolvedValue({ is_sandbox: true, renewal_normal: false, active: false, state: 'none', pending_order: order });
  const user = userEvent.setup(); view(<SubscriptionPage />);
  await user.click(await screen.findByRole('button', { name: 'Continue existing order' }));
  await screen.findByText(/Payment received by TikTok/);
  expect(subscriptions.createSubscriptionOrder).not.toHaveBeenCalled();
  expect(sdk.subscribe).toHaveBeenCalledWith('T1', false);
});
it('requires a supported SDK before starting a new order', async () => {
  vi.mocked(sdk.canIUse).mockReturnValue(false);
  const user = userEvent.setup(); view(<SubscriptionPage />);
  await user.click(await screen.findByRole('button', { name: /monthly.*USD 4.99/i }));
  expect(await screen.findByText('Update TikTok to manage subscriptions.')).toBeTruthy();
  expect(subscriptions.createSubscriptionOrder).not.toHaveBeenCalled();
});
it('authorizes profile only after an explicit click', async () => {
  const user = userEvent.setup(); view(<ProfilePage />);
  await screen.findByText('visitor-u1');
  expect(account.connectProfile).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Connect TikTok profile' }));
  expect(await screen.findByText('Joyce')).toBeTruthy();
});
it('history resumes the saved episode and disables unavailable titles', async () => {
  vi.mocked(account.getHistory).mockResolvedValue({ has_more: false, items: [
    { drama_id: 1, last_seq: 6, position_seconds: 42, updated_at: new Date().toISOString(), title: 'Story', cover_url: '', available: true },
    { drama_id: 2, last_seq: 2, position_seconds: 3, updated_at: new Date().toISOString(), title: 'Offline', cover_url: '', available: false },
  ] }); view(<HistoryPage />);
  expect((await screen.findByRole('link', { name: /Continue watching/ })).getAttribute('href')).toBe('/playlet/theater?id=1&seq=6');
  expect(screen.getByText('This story is currently unavailable.')).toBeTruthy();
});
it('wallet does not turn purchase totals into a balance and labels test orders', async () => {
  vi.mocked(account.getWallet).mockResolvedValue({ beans_balance: null, has_more: false, items: [
    { id: 'b1', title: 'Story', kind: 'beans', status: 'paid', is_sandbox: true, token_amount: 100, created_at: new Date().toISOString() },
  ] }); view(<WalletPage />);
  expect(await screen.findByText('100 Beans')).toBeTruthy();
  expect(screen.getByText(/paid · Test order/)).toBeTruthy();
  expect(screen.getByText(/Your Beans balance is managed by TikTok/)).toBeTruthy();
});
