import type { components } from '../../../../packages/api-types/schema';
import { apiFetch } from '../minis/session';
import { MOCK_API_ENABLED } from './config';
import { setPreviewSubscription } from './subscription-preview';

export type SubscriptionStatus = components['schemas']['SubscriptionStatusOut'];
export type SubscriptionTier = components['schemas']['SubscriptionTierOut'];
export type SubscriptionOrder = components['schemas']['SubscriptionOrderStatusOut'];
export type PlatformSubscription = components['schemas']['PlatformSubscriptionOut'];
type CreatedOrder = components['schemas']['SubscriptionOrderOut'];
export type SubscriptionQuery = components['schemas']['SubscriptionOrderQueryOut'];
let preview: SubscriptionStatus = { active: false, state: 'none', renewal_normal: false, is_sandbox: true };
const orders = new Map<string, SubscriptionOrder>();
let serial = 0;

export async function getSubscription(): Promise<SubscriptionStatus> {
  if (!MOCK_API_ENABLED) return apiFetch('/subscriptions/me');
  return structuredClone(preview);
}
export async function getPlatformSubscriptions(): Promise<PlatformSubscription[]> {
  if (!MOCK_API_ENABLED) return apiFetch('/subscriptions/platform');
  if (!preview.subscription_id || ['expired', 'revoked'].includes(preview.state)) return [];
  return [{ subscription_id: preview.subscription_id, tier_id: 'preview_monthly',
    state: preview.state as 'active' | 'cancel' | 'onhold', rights_valid: preview.active,
    renewal_normal: Boolean(preview.renewal_normal), end_time: preview.benefit_end_time ?? null, is_sandbox: true }];
}
export async function getSubscriptionTiers(): Promise<SubscriptionTier[]> {
  if (!MOCK_API_ENABLED) {
    const platform = /iPhone|iPad|iPod/i.test(navigator.userAgent) ? 'iphone' : 'android';
    return apiFetch(`/subscriptions/tiers?device_platform=${platform}`);
  }
  return [{ tier_id: 'preview_monthly', price: '4.99', currency: 'USD', deduct_cycle: 'MONTHLY', is_sandbox: true }];
}
export async function createSubscriptionOrder(tierId: string, subscriptionId?: string): Promise<CreatedOrder> {
  if (!MOCK_API_ENABLED) return apiFetch(subscriptionId
    ? `/subscriptions/${encodeURIComponent(subscriptionId)}/reactivate` : '/subscriptions', {
    method: 'POST', body: subscriptionId ? undefined : JSON.stringify({ tier_id: tierId }),
  });
  const order = { order_id: `preview_sub_${++serial}`, trade_order_id: `preview_trade_${serial}`,
    kind: subscriptionId ? 'reactivate' as const : 'create' as const, status: 'created' as const,
    subscription_id: subscriptionId ?? null };
  orders.set(order.order_id, order); preview.pending_order = order;
  return { order_id: order.order_id, trade_order_id: order.trade_order_id };
}
export async function getSubscriptionOrder(id: string): Promise<SubscriptionOrder> {
  if (!MOCK_API_ENABLED) return apiFetch(`/orders/subscriptions/${encodeURIComponent(id)}`);
  const order = orders.get(id); if (!order) throw new Error('Unknown preview order');
  return structuredClone(order);
}
export async function querySubscriptionOrder(id: string): Promise<SubscriptionQuery> {
  if (!MOCK_API_ENABLED) return apiFetch(`/orders/subscriptions/${encodeURIComponent(id)}/query`, { method: 'POST' });
  const order = await getSubscriptionOrder(id);
  return { order, platform_status: order.status === 'confirmed' ? 'SUCCESS' : 'PENDING',
    awaiting_webhook: order.status === 'created' };
}
export async function pollSubscriptionOrder(id: string, signal: AbortSignal, timeout = 20_000): Promise<SubscriptionOrder> {
  const deadline = Date.now() + timeout;
  for (;;) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    const order = await getSubscriptionOrder(id);
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    if (order.status !== 'created' || Date.now() >= deadline) return order;
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
      const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, 1500);
      signal.addEventListener('abort', abort, { once: true });
    });
  }
}
export function previewSubscriptionState(state: SubscriptionStatus['state']): void {
  if (!MOCK_API_ENABLED) throw new Error('Preview disabled');
  const active = ['active', 'cancel'].includes(state);
  preview = { active, state, subscription_id: state === 'none' ? null : 'preview_subscription',
    renewal_normal: state === 'active', is_sandbox: true,
    benefit_end_time: new Date(Date.now() + 30 * 86400_000).toISOString(), pending_order: preview.pending_order };
  setPreviewSubscription(active);
}
export function completePreviewSubscription(id: string): void {
  if (!MOCK_API_ENABLED) throw new Error('Preview disabled');
  const order = orders.get(id); if (!order) throw new Error('Unknown preview order');
  order.status = 'confirmed'; order.subscription_id = 'preview_subscription';
  previewSubscriptionState('active'); preview.pending_order = null;
}
