import { useCallback, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { BottomNav } from '../components/BottomNav';
import { DramaCard } from '../components/DramaCard';
import { useDramaList } from '../hooks/useDramaApi';
import { preloadDramaEpisode } from '../plugins/minis-player';
import { preloadTheaterPageCode } from '../router/lazy-pages';
import type { DramaSummary } from '../types/drama';

export function SquarePage() {
  const { data, loading, error } = useDramaList();
  const [query, setQuery] = useState('');
  const [slide, setSlide] = useState(0);
  const rail = useRef<HTMLDivElement>(null);
  const dramas = useMemo(() => [...new Map((data ?? []).map(d => [d.id, d])).values()], [data]);
  const results = dramas.filter(d => d.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const featured = dramas.slice(0, 5);
  const preloadOnIntent = useCallback((drama: DramaSummary) => {
    if (drama.preloadEpisode) void preloadDramaEpisode(drama, drama.preloadEpisode);
    void preloadTheaterPageCode();
  }, []);
  return <main className="app-shell discovery-page">
    <header className="discovery-header">
      <label className="catalog-search"><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10" cy="10" r="7" /><path d="m15 15 6 6" /></svg><input type="search" aria-label="Search dramas" placeholder="Search stories" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <Link className="profile-shortcut" to="/playlet/profile" aria-label="Your profile"><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="8" r="4" /><path d="M4 22v-2a8 8 0 0 1 16 0v2" /></svg></Link>
      <Link className="history-shortcut" to="/playlet/history">History</Link>
    </header>
    {loading ? <p className="page-state" role="status">Loading stories…</p> : error ? <div className="page-state" role="alert"><p>{error}</p><button onClick={() => window.location.reload()}>Try again</button></div> : !dramas.length ? <p className="page-state">New stories are on the way.</p> : query.trim() ?
      <section className="catalog-section" aria-label="Search results"><h1>Search results</h1><p className="result-count">{results.length} stories</p><div className="catalog-grid">{results.map(d => <DramaCard key={d.id} drama={d} onPreloadIntent={() => preloadOnIntent(d)} />)}</div>{!results.length && <p>Try another title.</p>}</section> : <>
      <section aria-label="Featured stories" className="portrait-feature">
        <div className="portrait-carousel" ref={rail} onScroll={() => {
          const el = rail.current; if (!el) return;
          const cards = Array.from(el.children) as HTMLElement[];
          const center = el.scrollLeft + el.clientWidth / 2;
          const nearest = cards.reduce((best, card, i) => Math.abs(card.offsetLeft + card.offsetWidth / 2 - center) < Math.abs(cards[best].offsetLeft + cards[best].offsetWidth / 2 - center) ? i : best, 0);
          setSlide(nearest);
        }}>{featured.map(d => <DramaCard key={d.id} drama={d} featured onPreloadIntent={() => preloadOnIntent(d)} />)}</div>
        <div className="carousel-dots" aria-label="Choose featured story">{featured.map((d, i) => <button key={d.id} aria-label={`Show ${d.title}`} aria-current={slide === i ? 'true' : undefined} onClick={() => {
          const el = rail.current; const card = el?.children[i] as HTMLElement | undefined;
          if (el && card) el.scrollTo({ left: card.offsetLeft - (el.clientWidth - card.offsetWidth) / 2, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
        }} />)}</div>
      </section>
      <section className="catalog-section" aria-label="TOP"><h2>TOP</h2><div className="poster-rail">{dramas.slice(0, 5).map(d => <DramaCard key={d.id} drama={d} onPreloadIntent={() => preloadOnIntent(d)} />)}</div></section>
      <section className="catalog-section" aria-label="Trending"><h2>Trending</h2><div className="catalog-grid">{dramas.map(d => <DramaCard key={d.id} drama={d} onPreloadIntent={() => preloadOnIntent(d)} />)}</div></section>
    </>}
    <BottomNav />
  </main>;
}
