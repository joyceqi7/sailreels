/**
 * Unlock flows. The backend decides access; these helpers only drive the client UI steps.
 *
 * IAA placement rules (hard requirement, review will reject otherwise):
 * - Rewarded ad only (a) after an episode ends naturally, before the next one, or
 *   (b) when the user actively skips/seeks into a locked episode.
 * - Never auto-trigger mid-episode without user action, never during auto-advance without a user tap.
 */
import { pay, showRewardedAd, subscribe, supportsRewardedAd } from './sdk';
import { apiFetch } from './session';
import { AD_UNIT_IDS } from './ad-config';
import type { components } from '../../../../packages/api-types/schema';

export type EpisodeAccess = components['schemas']['AccessOut'];
export type Access = EpisodeAccess['access'];

export function getEpisodeAccess(dramaId: number, seq: number) {
  return apiFetch<EpisodeAccess>(`/dramas/${dramaId}/episodes/${seq}/access`);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export type BeansOrderStatus = components['schemas']['OrderStatusOut']['status'];

/** Can resume the SAME order after a panel/network timeout; never creates another charge. */
export async function pollBeansOrder(orderId: string, timeoutMs = 20_000): Promise<BeansOrderStatus> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { status } = await apiFetch<components['schemas']['OrderStatusOut']>(
      `/orders/beans/${encodeURIComponent(orderId)}`);
    if (status === 'paid' || status === 'refunded' || status === 'failed') return status;
    await sleep(Math.min(1500, Math.max(0, deadline - Date.now())));
  }
  return 'created';
}

async function hasEpisodeAccess(dramaId: number, seq: number): Promise<boolean> {
  const result = await getEpisodeAccess(dramaId, seq);
  return ['free', 'unlocked', 'subscribed'].includes(result.access) &&
    result.episode?.seq === seq && result.episode.locked === false;
}

/** Returns true when the backend confirms the unlock (webhook processed). */
export async function unlockWithBeans(dramaId: number, seq: number, timeoutMs = 20_000): Promise<boolean> {
  const order = await apiFetch<components['schemas']['BeansOrderOut']>('/orders/beans', {
    method: 'POST',
    body: JSON.stringify({ drama_id: dramaId, seq }),
  });
  await pay(order.trade_order_id);
  if (await pollBeansOrder(order.order_id, timeoutMs) !== 'paid') return false;
  // Sandbox-blocked orders can be paid without granting rights. The access service is authoritative.
  return hasEpisodeAccess(dramaId, seq);
}

/** Returns true when the ad was fully watched and the backend granted the episode. */
export async function unlockWithAd(dramaId: number, seq: number, adUnitId: string = AD_UNIT_IDS.rewarded): Promise<boolean> {
  if (!supportsRewardedAd()) throw new Error('rewarded_ad_unsupported'); // UI: prompt TikTok update
  const { nonce } = await apiFetch<components['schemas']['AdNonceOut']>('/ads/rewarded/nonce', {
    method: 'POST',
    body: JSON.stringify({ drama_id: dramaId, seq }),
  });
  const ended = await showRewardedAd(adUnitId);
  if (!ended) return false;
  await apiFetch('/ads/rewarded/claim', { method: 'POST', body: JSON.stringify({ nonce }) });
  return hasEpisodeAccess(dramaId, seq);
}

export type SubscriptionStatus = components['schemas']['SubscriptionStatusOut'];

export async function startSubscription(tierId: string, timeoutMs = 30_000): Promise<boolean> {
  const order = await apiFetch<components['schemas']['SubscriptionOrderOut']>('/subscriptions', {
    method: 'POST',
    body: JSON.stringify({ tier_id: tierId }),
  });
  await subscribe(order.trade_order_id);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const s = await apiFetch<SubscriptionStatus>('/subscriptions/me');
    if (s.active) return true;
    await sleep(2000);
  }
  return false;
}
