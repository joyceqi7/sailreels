import type { components } from '../../../../packages/api-types/schema';
import { apiFetch } from '../minis/session';
import { ApiRequestError } from '../minis/session';
import { MOCK_API_ENABLED } from './config';
import { MOCK_CATALOG, MOCK_EPISODES, grantPreviewRight, hasPreviewRight } from './catalog-mock';

export type UnlockOptions = components['schemas']['UnlockOptionsOut'];
export type BeansOffer = components['schemas']['BeansOfferOut'];
export type BeansOrder = components['schemas']['BeansOrderOut'];
export type PendingOrder = Pick<BeansOrder, 'order_id'> & Partial<Pick<BeansOrder, 'trade_order_id'>>;
export type BeansStatus = components['schemas']['OrderStatusOut']['status'];
type PreviewOrder = BeansOrder & { dramaId: string; seqs: number[]; status: BeansStatus };
const orders = new Map<string, PreviewOrder>();
const nonces = new Map<string, { dramaId: string; seq: number; issuedAt: number }>();
let nextId = 0;
const pendingOrders = new Map<string, PendingOrder>();
const pendingKey = (dramaId: string, seq: number) => `${dramaId}:${seq}`;

export function rememberPendingOrder(dramaId: string, seq: number, order?: PendingOrder): void {
  const key = pendingKey(dramaId, seq);
  if (order) pendingOrders.set(key, order);
  else pendingOrders.delete(key);
}

/** Survives closing/reopening the panel. Validate ownership on the API before exposing a cached ID. */
export async function restorePendingOrder(dramaId: string, seq: number): Promise<PendingOrder | undefined> {
  const key = pendingKey(dramaId, seq), order = pendingOrders.get(key);
  if (!order) return undefined;
  try {
    if (['created', 'paid'].includes(await orderStatus(order.order_id))) return order;
    pendingOrders.delete(key);
  } catch (error) {
    if (!(error instanceof ApiRequestError) || error.status !== 404) throw error;
    pendingOrders.delete(key);
  }
  return undefined;
}

/** The live branch always delegates prices and fulfillment to the backend. */
export async function getUnlockOptions(dramaId: string, seq: number): Promise<UnlockOptions> {
  if (!MOCK_API_ENABLED) return apiFetch(`/dramas/${dramaId}/episodes/${seq}/unlock-options`);
  const drama = MOCK_CATALOG.find(item => String(item.id) === dramaId);
  if (!drama || seq <= drama.free_episodes || seq > drama.total_episodes || hasPreviewRight(dramaId, seq)) {
    throw new Error('not_unlockable');
  }
  return { drama_id: drama.id, seq, rewarded_ad: true, offers: ([1, 3, 10] as const).map(quantity => {
    const seqs = Array.from({ length: quantity }, (_, index) => seq + index);
    return { quantity, episode_seqs: seqs, token_amount: drama.unlock_price_beans * quantity,
      available: seqs.every(n => MOCK_EPISODES[dramaId]?.[n - 1] && !hasPreviewRight(dramaId, n)) };
  }) };
}

export async function createBeansOrder(dramaId: string, seq: number, offer: BeansOffer): Promise<BeansOrder> {
  if (!MOCK_API_ENABLED) return apiFetch('/orders/beans', { method: 'POST', body: JSON.stringify({
    drama_id: Number(dramaId), seq, quantity: offer.quantity, expected_token_amount: offer.token_amount,
  }) });
  const actual = (await getUnlockOptions(dramaId, seq)).offers.find(item => item.quantity === offer.quantity);
  if (!actual?.available || actual.token_amount !== offer.token_amount) throw new Error('offer_changed');
  const order = { order_id: `preview_${++nextId}`, trade_order_id: `preview_trade_${nextId}`,
    dramaId, seqs: actual.episode_seqs, status: 'created' as const };
  orders.set(order.order_id, order);
  return { order_id: order.order_id, trade_order_id: order.trade_order_id };
}

export async function orderStatus(orderId: string): Promise<BeansStatus> {
  if (!MOCK_API_ENABLED) {
    const result = await apiFetch<components['schemas']['OrderStatusOut']>(`/orders/beans/${encodeURIComponent(orderId)}`);
    return result.status;
  }
  const order = orders.get(orderId);
  if (!order) throw new Error('unknown_order');
  return order.status;
}

export async function waitForOrder(orderId: string, timeoutMs = 20_000): Promise<BeansStatus> {
  const deadline = Date.now() + timeoutMs;
  do {
    const status = await orderStatus(orderId);
    if (status !== 'created') return status;
    const remaining = deadline - Date.now();
    if (remaining <= 0) return 'created';
    await new Promise(resolve => setTimeout(resolve, Math.min(1500, remaining)));
  } while (Date.now() < deadline);
  return 'created';
}

/** Explicit preview controls only: no network callback, balance, or production entitlement is forged. */
export function completePreviewPayment(orderId: string): void {
  if (!MOCK_API_ENABLED) throw new Error('preview_disabled');
  const order = orders.get(orderId);
  if (!order) throw new Error('unknown_order');
  order.status = 'paid';
  order.seqs.forEach(seq => grantPreviewRight(order.dramaId, seq));
}

export async function issueRewardNonce(dramaId: string, seq: number): Promise<string> {
  if (!MOCK_API_ENABLED) {
    const result = await apiFetch<components['schemas']['AdNonceOut']>('/ads/rewarded/nonce', {
      method: 'POST', body: JSON.stringify({ drama_id: Number(dramaId), seq }),
    });
    return result.nonce;
  }
  await getUnlockOptions(dramaId, seq);
  const nonce = `preview_nonce_${++nextId}`;
  nonces.set(nonce, { dramaId, seq, issuedAt: Date.now() });
  return nonce;
}

export async function claimReward(nonce: string): Promise<void> {
  if (!MOCK_API_ENABLED) {
    await apiFetch('/ads/rewarded/claim', { method: 'POST', body: JSON.stringify({ nonce }) });
    return;
  }
  const reward = nonces.get(nonce);
  if (!reward || Date.now() - reward.issuedAt > 600_000) throw new Error('invalid_nonce');
  nonces.delete(nonce);
  grantPreviewRight(reward.dramaId, reward.seq);
}
