import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Dialog } from './Dialog';
import { MOCK_API_ENABLED } from '../api/config';
import { loadPlayableEpisode } from '../api/access';
import { ApiRequestError } from '../minis/session';
import { pay, showRewardedAd, supportsRewardedAd } from '../minis/sdk';
import { REWARDED_AD_CONFIGURED } from '../minis/ad-config';
import { IAP_ENABLED } from '../monetization';
import { claimReward, completePreviewPayment, createBeansOrder, getUnlockOptions, issueRewardNonce,
  orderStatus, waitForOrder, type BeansOffer, type PendingOrder, type UnlockOptions } from '../api/monetization';
import { rememberPendingOrder, restorePendingOrder } from '../api/monetization';
import type { EpisodeSource } from '../types/drama';

export type UnlockReason = 'entry' | 'jump' | 'ended';
interface Props {
  dramaId: string; seq: number; reason: UnlockReason;
  onClose: () => void; onUnlocked: (episode: EpisodeSource) => Promise<void>;
}
type Preview = { kind: 'payment' | 'ad'; decide: (result: 'complete' | 'close' | 'error' | 'pending') => void };

export function UnlockSheet({ dramaId, seq, reason, onClose, onUnlocked }: Props) {
  const [options, setOptions] = useState<UnlockOptions>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<PendingOrder>();
  const [preview, setPreview] = useState<Preview>();
  const [waiting, setWaiting] = useState(false);
  const active = useRef(true);
  const running = useRef(false);
  const previewRef = useRef<Preview | undefined>(undefined);
  const [canWatch, setCanWatch] = useState(() => MOCK_API_ENABLED || supportsRewardedAd());
  // Two different reasons the ad option can be unusable. No ad unit for this app is permanent —
  // hide the option so users aren't offered a reward the app can never show. An unsupported client
  // is fixable by the user, so keep the button visible and disabled with an upgrade prompt.
  const showAdOption = MOCK_API_ENABLED || REWARDED_AD_CONFIGURED;
  // With Beans available, a directly opened locked episode is sold rather than gated behind an ad. In
  // IAA-only mode the ad is the sole unlock, and the user's tap on that episode is the triggering action.
  const adBlockedOnEntry = IAP_ENABLED && reason === 'entry';
  useEffect(() => {
    active.current = true;
    Promise.all([getUnlockOptions(dramaId, seq), restorePendingOrder(dramaId, seq)]).then(([result, order]) => {
      if (active.current) { setOptions(result); setPending(order); setWaiting(Boolean(order)); }
    })
      .catch(() => { if (active.current) setLoadError(true); });
    return () => { active.current = false; previewRef.current?.decide('close'); };
  }, [dramaId, seq, reload]);

  const askPreview = (kind: Preview['kind']) => new Promise<'complete' | 'close' | 'error' | 'pending'>(resolve => {
    const prompt = { kind, decide: resolve };
    previewRef.current = prompt; setPreview(prompt);
  });
  const choosePreview = (result: 'complete' | 'close' | 'error' | 'pending') => {
    previewRef.current?.decide(result); previewRef.current = undefined; setPreview(undefined);
  };
  const verifyAccess = async () => {
    const episode = await loadPlayableEpisode(dramaId, seq);
    if (active.current) await onUnlocked(episode);
  };
  const checkOrder = async (order: PendingOrder, wait = true) => {
    const status = wait ? await waitForOrder(order.order_id) : await orderStatus(order.order_id);
    if (!active.current) return;
    if (status === 'paid') {
      try {
        await verifyAccess();
        rememberPendingOrder(dramaId, seq);
        if (active.current) setPending(undefined);
      } catch {
        setWaiting(false);
        setMessage('Payment confirmed. Viewing access is not ready yet. Check this order again before purchasing.');
      }
    }
    else if (status === 'created') {
      setWaiting(true); setMessage('Your order is processing. Check this order before making another purchase.');
    } else {
      rememberPendingOrder(dramaId, seq); setPending(undefined); setWaiting(false);
      setMessage('This order did not unlock the episode.');
    }
  };
  const perform = async (action: () => Promise<void>) => {
    if (running.current) return;
    running.current = true; setBusy(true); setMessage('');
    try { await action(); }
    catch (error) {
      if (!active.current) return;
      if (error instanceof ApiRequestError && error.orderId) {
        const uncertain = { order_id: error.orderId };
        rememberPendingOrder(dramaId, seq, uncertain); setPending(uncertain); setWaiting(true);
        setMessage('Order confirmation was delayed. Check this order before making another purchase.');
      } else if (error instanceof ApiRequestError && error.status === 409) {
        try { await verifyAccess(); }
        catch {
          if (active.current) {
            setOptions(undefined); setLoadError(false); setReload(value => value + 1);
            setMessage('Your access or price has changed. Please check the updated options.');
          }
        }
      } else if (error instanceof ApiRequestError && error.status === 429) {
        setMessage(IAP_ENABLED ? 'Your ad reward limit has been reached. Try again later or unlock with Beans.'
          : 'Your ad reward limit has been reached. Try again later.');
      } else setMessage('Unable to complete the unlock. Check your order or try again.');
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  };
  const buy = (offer: BeansOffer) => perform(async () => {
    const order = await createBeansOrder(dramaId, seq, offer);
    if (!active.current) return;
    setPending(order);
    rememberPendingOrder(dramaId, seq, order);
    if (MOCK_API_ENABLED) {
      const result = await askPreview('payment');
      if (!active.current) return;
      if (result === 'close') {
        rememberPendingOrder(dramaId, seq); setPending(undefined);
        setMessage('Payment cancelled. No episodes were unlocked.'); return;
      }
      if (result === 'error') { setWaiting(true); setMessage('Payment could not be confirmed. Check this order.'); return; }
      if (result === 'pending') { await checkOrder(order, false); return; }
      completePreviewPayment(order.order_id);
    } else {
      // An SDK timeout/cancel is not proof that payment failed; keep the order available to check.
      try { await pay(order.trade_order_id); }
      catch { if (active.current) await checkOrder(order, false); return; }
    }
    if (active.current) await checkOrder(order);
  });
  const watch = () => perform(async () => {
    if (adBlockedOnEntry) return;
    // The button is hidden without an ad unit; this guards a stale render holding the old options.
    if (!MOCK_API_ENABLED && !REWARDED_AD_CONFIGURED) {
      setMessage('Rewarded ads are not available yet.'); return;
    }
    if (!MOCK_API_ENABLED && !supportsRewardedAd()) {
      setCanWatch(false); setMessage('Update TikTok to watch rewarded ads.'); return;
    }
    const nonce = await issueRewardNonce(dramaId, seq);
    if (!active.current) return;
    let ended = false;
    if (MOCK_API_ENABLED) {
      const result = await askPreview('ad');
      if (result === 'error') throw new Error('preview_ad_error');
      ended = result === 'complete';
    } else ended = await showRewardedAd();
    if (!active.current) return;
    if (!ended) { setMessage('Watch the full ad to unlock this episode.'); return; }
    await claimReward(nonce);
    await verifyAccess();
  });

  if (preview) return <Dialog title={preview.kind === 'ad' ? 'Preview rewarded ad' : 'Preview payment'}
    onClose={() => choosePreview('close')}>
    <p>This preview does not charge money or show a real ad.</p>
    <button className="primary-action" onClick={() => choosePreview('complete')}>
      {preview.kind === 'ad' ? 'Finish watching' : 'Complete preview payment'}</button>
    <button className="secondary-action" onClick={() => choosePreview('close')}>
      {preview.kind === 'ad' ? 'Close ad early' : 'Cancel payment'}</button>
    {preview.kind === 'payment' && <button className="secondary-action" onClick={() => choosePreview('pending')}>Simulate delayed confirmation</button>}
    <button className="secondary-action" onClick={() => choosePreview('error')}>Simulate error</button>
  </Dialog>;
  return <Dialog title={`Unlock episode ${seq}`} busy={busy} onClose={onClose}>
    {IAP_ENABLED ? <>
      <p>Choose how you would like to keep watching.</p>
      <Link className="secondary-action" to="/playlet/subscription">Explore VIP membership</Link>
    </> : <p>Watch a short ad to keep watching.</p>}
    {MOCK_API_ENABLED && <p className="preview-label">Demo preview · no real purchases</p>}
    {!options && !loadError && <p role="status">Loading unlock options…</p>}
    {loadError && <p role="alert">Unable to load unlock options. <button onClick={() => {
      setLoadError(false); setReload(value => value + 1);
    }}>Try again</button></p>}
    {options && <>
      {IAP_ENABLED && <div className="beans-offers">{options.offers.map(offer => <button key={offer.quantity}
        disabled={busy || Boolean(pending) || !offer.available} onClick={() => void buy(offer)}>
        <strong>{offer.quantity === 1 ? 'Single episode' : `${offer.quantity} episodes`}</strong>
        <span>{offer.token_amount} Beans</span>
        <small>{offer.available ? `Episodes ${offer.episode_seqs[0]}–${offer.episode_seqs.at(-1)}` : 'Not enough locked episodes'}</small>
      </button>)}</div>}
      {options.rewarded_ad && showAdOption && <button className="primary-action" disabled={busy || Boolean(pending) || adBlockedOnEntry || !canWatch}
        onClick={() => void watch()}>Watch an ad · unlock this episode</button>}
      {adBlockedOnEntry && <p className="help-text">Watch a free episode first to use a rewarded ad between episodes.</p>}
      {showAdOption && !canWatch && <p className="help-text">
        Update TikTok to watch rewarded ads.{IAP_ENABLED && ' You can also unlock with Beans.'}</p>}
      {!IAP_ENABLED && !(options.rewarded_ad && showAdOption) && <p className="help-text">
        Unlocking is not available right now. Please try again later.</p>}
    </>}
    {pending && <>
      <p className="help-text">Order: {pending.order_id}</p>
      <button className="secondary-action" disabled={busy} onClick={() => void perform(() => checkOrder(pending, false))}>Check existing order</button>
      {MOCK_API_ENABLED && waiting && <button className="secondary-action" disabled={busy}
        onClick={() => void perform(async () => { completePreviewPayment(pending.order_id); await checkOrder(pending, false); })}>
        Complete delayed preview payment</button>}
    </>}
    {message && <p role="status" className="unlock-message">{message}</p>}
    {busy && <p role="status">Checking your unlock…</p>}
  </Dialog>;
}
