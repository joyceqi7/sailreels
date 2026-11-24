import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { DramaCard } from '../components/DramaCard';
import { useDramaList } from '../hooks/useDramaApi';
import { BottomNav } from '../components/BottomNav';
import { connectProfile, getHistory, getProfile, getWallet, type History, type Wallet } from '../api/account';
import { getSubscription, type SubscriptionStatus } from '../api/subscriptions';
import { MOCK_API_ENABLED } from '../api/config';
import { APP_NAME } from '../app-identity';
import { IAP_ENABLED } from '../monetization';
import type { ProfileResponse } from '../minis/session';

export function ProfilePage() {
  const { data: dramas = [] } = useDramaList();
  const [recent, setRecent] = useState<History>();
  useEffect(() => { let active = true; void Promise.resolve(getHistory()).then(data => { if (active) setRecent(data); }).catch(() => undefined); return () => { active = false; }; }, []);
  const [profile, setProfile] = useState<ProfileResponse>();
  const [subscription, setSubscription] = useState<SubscriptionStatus>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false), [attempt, setAttempt] = useState(0);
  const alive = useRef(true);
  const until = subscription?.benefit_end_time
    ? new Date(subscription.benefit_end_time).toLocaleDateString('en-US') : undefined;
  const vipStatus = subscription?.state === 'onhold' ? 'Payment needs attention'
    : subscription?.state === 'cancel' && subscription.active ? `Auto-renewal off · ends ${until ?? 'soon'}`
    : subscription?.active ? `Active${until ? ` until ${until}` : ''}`
    : 'Unlock every episode. No interruptions.';
  const vipAction = subscription?.state === 'onhold' ? 'Fix' : subscription?.active ? 'Manage' : 'Join';
  useEffect(() => {
    alive.current = true; setMessage('');
    void Promise.all([getProfile(), IAP_ENABLED ? getSubscription() : undefined]).then(([p, s]) => {
      if (alive.current) { setProfile(p); setSubscription(s); }
    }).catch(() => { if (alive.current) setMessage('Unable to load your account. Please try again.'); });
    return () => { alive.current = false; };
  }, [attempt]);
  const connect = async () => {
    if (busy) return; setBusy(true); setMessage('');
    try { const result = await connectProfile(); if (alive.current) setProfile(result); }
    catch { if (alive.current) setMessage('Profile access was not completed. You can keep watching without sharing your profile.'); }
    finally { if (alive.current) setBusy(false); }
  };
  return <main className="app-shell account-page profile-page"><Link className="back-link" to="/playlet/square">‹ Home</Link><h1>Profile</h1>
    {MOCK_API_ENABLED && <p className="preview-label">Demo preview · account data is not live</p>}
    <section className="profile-identity">{profile?.avatar_url ? <img src={profile.avatar_url} alt="" /> : <span aria-hidden="true">S</span>}
      <div><h2>{profile?.nickname || (profile?.open_id ? `visitor-${profile.open_id.slice(-6)}` : 'Drama fan')}</h2><p className="profile-id">ID: {profile?.open_id ?? '…'} {profile && <button aria-label="Copy user ID" onClick={() => { void navigator.clipboard?.writeText(profile.open_id).then(() => setMessage('ID copied')).catch(() => setMessage('Unable to copy ID.')); }}>Copy</button>}</p></div></section>
    {IAP_ENABLED && <Link className={`vip-card${subscription?.state === 'onhold' ? ' is-alert' : ''}`} to="/playlet/subscription">
      <div><strong>{APP_NAME} VIP</strong><small>{vipStatus}</small></div><span>{vipAction} ›</span></Link>}
    <section className="profile-recommendations" aria-label="Top Shorts"><h2>Top Shorts</h2><div className="poster-rail">{dramas.slice(0, 5).map(d => <DramaCard key={d.id} drama={d} />)}</div></section>
    <section aria-label="Recent history"><div className="section-title"><h2>History</h2><Link to="/playlet/history">See all ›</Link></div>{recent?.items.length ? <HistoryCards items={recent.items.slice(0, 3)} /> : <p className="help-text">Your watched stories will appear here.</p>}</section>
    <button className="secondary-action" disabled={busy || !profile} onClick={() => void connect()}>Connect TikTok profile</button>
    <p className="help-text">Share your name and photo only when you choose to connect.</p>
    <div className="account-menu">{IAP_ENABLED && <Link to="/playlet/wallet"><span>Wallet & purchases</span><small>View your orders ›</small></Link>}
      <Link to="/playlet/history"><span>Watch history</span><small>Continue a story ›</small></Link></div>
    {message && <p role="status">{message} <button onClick={() => setAttempt(a => a + 1)}>Try again</button></p>}
    <BottomNav /></main>;
}

export function WalletPage() {
  const [wallet, setWallet] = useState<Wallet>(), [error, setError] = useState(false), [busy, setBusy] = useState(false);
  const alive = useRef(true), loading = useRef(false);
  const load = async (offset = 0) => {
    if (loading.current) return; loading.current = true; setBusy(true); setError(false);
    try { const data = await getWallet(offset); if (alive.current) setWallet(previous => ({ ...data,
      items: offset ? [...(previous?.items ?? []), ...data.items] : data.items })); }
    catch { if (alive.current) setError(true); }
    finally { loading.current = false; if (alive.current) setBusy(false); }
  };
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, []);
  return <main className="app-shell account-page"><Link className="back-link" to="/playlet/profile">‹ My account</Link><h1>Wallet & purchases</h1>
    {MOCK_API_ENABLED && <p className="preview-label">Demo preview · purchase history is not live</p>}
    <section className="wallet-note"><h2>Your TikTok Beans</h2><p>Your Beans balance is managed by TikTok. Check it in TikTok checkout.</p></section>
    <h2>Purchase history</h2>{wallet?.items.length === 0 && <p>No purchases yet. <Link to="/playlet/square">Find a story</Link></p>}
    <ol className="purchase-history">{wallet?.items.map(item => <li key={`${item.kind}:${item.id}`}><div><strong>{item.title}</strong>
      <small>{new Date(item.created_at).toLocaleDateString('en-US')} · {item.status}{item.is_sandbox ? ' · Test order' : ''}</small>
      <small className="order-reference">{item.id}</small></div><span>{item.kind === 'beans' ? `${item.token_amount} Beans`
        : item.actual_price ? `${item.currency ?? ''} ${item.actual_price}` : 'Amount unavailable'}
      {item.refund_price && <small>Refund {item.refund_currency ?? ''} {item.refund_price}</small>}</span></li>)}</ol>
    {error && <p role="alert">Unable to load purchases. <button disabled={busy} onClick={() => void load(wallet?.items.length ?? 0)}>Try again</button></p>}
    {wallet?.has_more && <button className="secondary-action" disabled={busy} onClick={() => void load(wallet.items.length)}>Load more purchases</button>}
    {busy && <p role="status">Loading purchases…</p>}<BottomNav /></main>;
}

export function HistoryPage() {
  const [history, setHistory] = useState<History>(), [error, setError] = useState(false), [busy, setBusy] = useState(false);
  const alive = useRef(true), loading = useRef(false);
  const load = async (offset = 0) => {
    if (loading.current) return; loading.current = true; setBusy(true); setError(false);
    try { const data = await getHistory(offset); if (alive.current) setHistory(previous => ({ ...data,
      items: offset ? [...(previous?.items ?? []), ...data.items] : data.items })); }
    catch { if (alive.current) setError(true); }
    finally { loading.current = false; if (alive.current) setBusy(false); }
  };
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, []);
  return <main className="app-shell account-page history-page"><Link className="back-link" to="/playlet/square">‹ Home</Link><h1>Watch history</h1>
    {MOCK_API_ENABLED && <p className="preview-label">Demo preview · progress lasts for this session</p>}
    {history?.items.length === 0 && <section className="account-empty"><h2>Your next story is waiting.</h2><p>Watch an episode and find it here when you return.</p><Link className="primary-action" to="/playlet/square">Explore dramas</Link></section>}
    <HistoryCards items={history?.items ?? []} />
    {error && <p role="alert">Unable to load history. <button disabled={busy} onClick={() => void load(history?.items.length ?? 0)}>Try again</button></p>}
    {history?.has_more && <button className="secondary-action" disabled={busy} onClick={() => void load(history.items.length)}>Load more history</button>}
    {busy && <p role="status">Loading history…</p>}<BottomNav /></main>;
}

function HistoryCards({ items }: { items: History['items'] }) {
  return <ol className="history-grid">{[...new Map(items.map(item => [item.drama_id, item])).values()].map(item => <li key={item.drama_id}>
    {item.available ? <Link aria-label={`Continue watching ${item.title}`} to={`/playlet/theater?id=${item.drama_id}&seq=${item.last_seq}`}><span className="history-cover">{item.cover_url && <img src={item.cover_url} alt="" loading="lazy" />}</span><h2>{item.title}</h2></Link>
      : <><span className="history-cover">{item.cover_url && <img src={item.cover_url} alt="" loading="lazy" />}</span><h2>{item.title}</h2><small>This story is currently unavailable.</small></>}
    <p>watched <span>EP{item.last_seq}</span></p>
  </li>)}</ol>;
}
