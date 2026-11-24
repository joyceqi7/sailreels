import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { BottomNav } from '../components/BottomNav';
import { Dialog } from '../components/Dialog';
import { MOCK_API_ENABLED } from '../api/config';
import { canIUse, hideSubscriptionRibbon, showSurfaceCoupon, subscribe } from '../minis/sdk';
import { ApiRequestError } from '../minis/session';
import { completePreviewSubscription, createSubscriptionOrder, getPlatformSubscriptions, getSubscription,
  getSubscriptionOrder, getSubscriptionTiers, pollSubscriptionOrder, previewSubscriptionState, querySubscriptionOrder,
  type PlatformSubscription, type SubscriptionOrder, type SubscriptionStatus, type SubscriptionTier } from '../api/subscriptions';

const date = (value?: string | null) => value ? new Date(value).toLocaleDateString('en-US') : 'Pending confirmation';
export function SubscriptionPage() {
  const [status, setStatus] = useState<SubscriptionStatus>();
  const [platform, setPlatform] = useState<PlatformSubscription[]>();
  const [tiers, setTiers] = useState<SubscriptionTier[]>([]);
  const [pending, setPending] = useState<SubscriptionOrder | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [message, setMessage] = useState('');
  const [coupon, setCoupon] = useState('');
  const [previewOrder, setPreviewOrder] = useState<string>();
  const alive = useRef(true), actionLock = useRef(false);
  const pollController = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    const [local, current, products] = await Promise.all([getSubscription(), getPlatformSubscriptions(), getSubscriptionTiers()]);
    if (!alive.current) return;
    setStatus(local); setPlatform(current); setTiers(products); setPending(local.pending_order ?? null); setLoadError(false);
  }, []);
  useEffect(() => {
    alive.current = true;
    void refresh().catch(() => { if (alive.current) setLoadError(true); });
    return () => { alive.current = false; pollController.current?.abort(); hideSubscriptionRibbon(); };
  }, [refresh]);
  const canCreate = Boolean(status && platform && !pending && platform.length === 0
    && !status.active && status.state !== 'onhold');
  useEffect(() => {
    if (MOCK_API_ENABLED || !canCreate) return;
    let active = true;
    void showSurfaceCoupon().then(value => {
      if (active) setCoupon(value);
      else hideSubscriptionRibbon(); // A late callback must not leave the ribbon on another page.
    });
    return () => { active = false; hideSubscriptionRibbon(); };
  }, [canCreate]);
  const perform = async (task: () => Promise<void>) => {
    if (actionLock.current) return;
    actionLock.current = true; setBusy(true); setMessage('');
    try { await task(); }
    catch (error) {
      if (!alive.current) return;
      if (error instanceof ApiRequestError && error.orderId) {
        // Also recovers an order that was accepted before the create response timed out.
        const order = await getSubscriptionOrder(error.orderId).catch(() => null);
        if (alive.current) setPending(order);
      }
      const detail = error instanceof ApiRequestError ? error.detail : '';
      setMessage(detail === 'subscription_reactivation_blocked'
        ? 'Your renewal is too close to reactivate here. Manage your subscription in your app store.'
        : detail === 'active_subscription_exists' || detail === 'subscription_state_conflict'
          ? 'Your subscription changed. Refresh its status before trying again.'
          : 'Unable to finish this request. Check your existing order before trying to purchase again.');
    } finally { actionLock.current = false; if (alive.current) setBusy(false); }
  };
  const checkOrder = async (order: SubscriptionOrder, wait = true) => {
    pollController.current?.abort();
    const controller = new AbortController(); pollController.current = controller;
    const result = wait ? await pollSubscriptionOrder(order.order_id, controller.signal) : await getSubscriptionOrder(order.order_id);
    if (!alive.current) return;
    if (result.status === 'created') {
      const query = await querySubscriptionOrder(order.order_id);
      if (!alive.current) return;
      setPending(result);
      setMessage(query.platform_status === 'SUCCESS'
        ? 'Payment received by TikTok. Your benefits are awaiting confirmation. Do not purchase again.'
        : 'Your order is still processing. Check this order again before making another purchase.');
    } else {
      await refresh();
      if (alive.current) setMessage(result.status === 'confirmed' ? 'Subscription confirmed.' : 'This order could not be completed.');
    }
  };
  const buy = (tierId = '') => perform(async () => {
    const reactivate = status?.state === 'cancel';
    const api = reactivate ? 'reactivateSubscription' : 'createSubscription';
    if (!MOCK_API_ENABLED && !canIUse(api)) { setMessage('Update TikTok to manage subscriptions.'); return; }
    const created = await createSubscriptionOrder(tierId, reactivate ? status?.subscription_id ?? undefined : undefined);
    if (!alive.current) return;
    const order = await getSubscriptionOrder(created.order_id);
    if (!alive.current) return;
    setPending(order);
    if (MOCK_API_ENABLED) { setPreviewOrder(order.order_id); return; }
    // Panel cancellation/errors still trigger a server check; callbacks never activate benefits.
    try { await subscribe(created.trade_order_id, reactivate); }
    finally { if (alive.current) await checkOrder(order); }
  });
  const onhold = status?.state === 'onhold' || platform?.some(s => s.state === 'onhold');
  const cancel = status?.state === 'cancel';
  const canReactivate = cancel && status.active && platform?.some(s => s.state === 'cancel'
    && s.subscription_id === status.subscription_id) && !onhold && !pending;
  return <main className="app-shell account-page">
    <Link className="back-link" to="/playlet/profile">‹ My account</Link>
    <section className="membership-heading"><span className="membership-mark" aria-hidden="true">S</span>
      <h1>Your next episode.<br />No interruptions.</h1><p>VIP unlocks all available episodes.</p></section>
    {MOCK_API_ENABLED && <p className="preview-label">Demo preview · no real purchases</p>}
    {loadError ? <p role="alert">Unable to load subscriptions. <button onClick={() => void perform(refresh)}>Try again</button></p>
      : !status ? <p role="status">Loading subscription…</p> : <>
      <section className="membership-status" aria-label="Subscription status">
        <h2>{onhold ? 'Payment needs attention' : cancel ? 'Auto-renewal is off' : status.active ? 'VIP is active' : 'Choose your VIP plan'}</h2>
        {status.subscription_id && <p>{status.active ? 'Benefits available until' : 'Last benefit period ends'} {date(status.benefit_end_time)}</p>}
        {cancel && <p>You keep your remaining benefits. Reactivate to turn auto-renewal back on.</p>}
        {onhold && <><p>Update your payment method or manage this subscription in Google Play or the App Store. A new plan cannot be purchased while payment is on hold.</p>
          <div className="store-links"><a href="https://play.google.com/store/account/subscriptions" target="_blank" rel="noreferrer">Google Play subscriptions</a>
            <a href="https://apps.apple.com/account/subscriptions" target="_blank" rel="noreferrer">App Store subscriptions</a></div>
          <p>{status.active ? 'Your current benefits are still available.' : 'Benefits are unavailable until renewal is confirmed.'}</p></>}
        {canReactivate && <button className="primary-action" disabled={busy} onClick={() => void buy()}>Reactivate subscription</button>}
        {platform && platform.length > 0 && !status.subscription_id && <p>We found an existing subscription. Its benefits are awaiting confirmation.</p>}
      </section>
      {canCreate && <section aria-label="Available plans">
        {coupon && <p className="platform-coupon">TikTok offer: {coupon}<small>The final offer and price appear in TikTok checkout.</small></p>}
        {tiers.length ? tiers.map(tier => <button className="subscription-plan" key={tier.tier_id} disabled={busy}
          onClick={() => void buy(tier.tier_id)}><span>{tier.deduct_cycle.toLowerCase().replaceAll('_', ' ')}<small>{tier.is_sandbox ? 'Test plan · no real charge' : 'Renews automatically. Cancel in your app store.'}</small></span>
          <strong>{tier.currency} {tier.price}</strong></button>) : <p>Subscription plans are not available yet. Please check back later.</p>}
        <p className="help-text">Review the recurring price, billing period and cancellation terms in TikTok before confirming.</p>
      </section>}
    </>}
    {pending && <section className="membership-status"><h2>Existing subscription order</h2><p className="help-text">{pending.order_id}</p>
      <button className="secondary-action" disabled={busy} onClick={() => void perform(() => checkOrder(pending))}>Check existing order</button>
      {pending.trade_order_id && <button className="secondary-action" disabled={busy} onClick={() => void perform(async () => {
        if (MOCK_API_ENABLED) { setPreviewOrder(pending.order_id); return; }
        const api = pending.kind === 'reactivate' ? 'reactivateSubscription' : 'createSubscription';
        if (!canIUse(api)) { setMessage('Update TikTok to manage subscriptions.'); return; }
        try { await subscribe(pending.trade_order_id!, pending.kind === 'reactivate'); }
        finally { if (alive.current) await checkOrder(pending); }
      })}>Continue existing order</button>}</section>}
    <button className="secondary-action" disabled={busy} onClick={() => void perform(refresh)}>Refresh subscription status</button>
    {message && <p role="status" className="account-message">{message}</p>}{busy && <p role="status">Checking subscription…</p>}
    {MOCK_API_ENABLED && <details className="preview-controls"><summary>Preview subscription states</summary>{(['none', 'active', 'cancel', 'onhold', 'expired', 'revoked'] as const).map(s =>
      <button key={s} disabled={busy || Boolean(pending)} onClick={() => { previewSubscriptionState(s); void refresh(); }}>{s}</button>)}</details>}
    {previewOrder && <Dialog title="Preview subscription" onClose={() => setPreviewOrder(undefined)}>
      <p>This preview does not charge money. Closing this panel leaves the existing order available to check.</p>
      <button className="primary-action" onClick={() => { completePreviewSubscription(previewOrder); setPreviewOrder(undefined); void refresh(); }}>Confirm preview subscription</button>
      <button className="secondary-action" onClick={() => setPreviewOrder(undefined)}>Simulate delayed confirmation</button>
    </Dialog>}
    <BottomNav />
  </main>;
}
