import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { BottomNav } from '../components/BottomNav';
import { ChevronUpIcon, DramaIcon } from '../components/Icons';
import { useDramaList } from '../hooks/useDramaApi';
import { useMinisPlayer } from '../hooks/useMinisPlayer';
import { useWatchProgress } from '../hooks/useWatchProgress';
import { loadPlayableEpisode } from '../api/access';
import { getProgress, type Progress } from '../api/account';
import type { Drama, DramaSummary, EpisodeSource } from '../types/drama';

/**
 * TikTok-style discovery feed: one item per drama, each playing that drama's free first episode.
 * Swiping (or finishing an episode) moves to the next drama; "Continue" opens the full theater.
 *
 * One Player instance serves the whole feed. Its drama identity is the constant FEED_ID so that
 * useMinisPlayer never rebuilds it; switching dramas goes through playNext(), which is safe because
 * every playback/preload config is built from the episode's own albumId.
 */
const FEED_ID = 'for-you';
const SWIPE_MS = 260;

type Loaded = EpisodeSource | 'unavailable';

export function ForYouPage() {
  const { data, loading, error } = useDramaList();
  const dramas = useMemo(() => (data ?? []).filter(d => d.episodeCount > 0), [data]);
  if (loading) return <main className="app-shell feed-page"><div className="page-state">Loading…</div><BottomNav /></main>;
  if (error || !dramas.length) return <main className="app-shell feed-page"><div className="page-state">
    <p>{error ?? 'New dramas are on the way.'}</p>
    <button onClick={() => window.location.reload()}>Try again</button></div><BottomNav /></main>;
  return <FeedContent dramas={dramas} />;
}

function FeedContent({ dramas }: { dramas: DramaSummary[] }) {
  const count = dramas.length;
  const wrap = useCallback((i: number) => ((i % count) + count) % count, [count]);
  const [index, setIndex] = useState(0);
  const [active, setActive] = useState<EpisodeSource>();
  const [loaded, setLoaded] = useState<Record<string, Loaded>>({});
  const [progress, setProgress] = useState<Record<string, Progress | null>>({});
  const [busy, setBusy] = useState(false);
  const [allUnavailable, setAllUnavailable] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const [settling, setSettling] = useState(false);
  const mounted = useRef(true);
  const busyRef = useRef(false);
  const stageRef = useRef<HTMLElement>(null);
  const touchStart = useRef<number | undefined>(undefined);
  const dragRef = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const cache = useRef<Record<string, Promise<Loaded>>>({});

  const drama = dramas[index];
  const nextDrama = count > 1 ? dramas[wrap(index + 1)] : undefined;
  const prevDrama = count > 1 ? dramas[wrap(index - 1)] : undefined;
  const nextSource = nextDrama && loaded[nextDrama.id];

  /** Episode 1 of a drama, resolved once. Locked/missing media is "unavailable", never playable. */
  const resolve = useCallback((target: DramaSummary): Promise<Loaded> => {
    cache.current[target.id] ??= loadPlayableEpisode(target.id, 1).catch((): Loaded => 'unavailable')
      .then(result => {
        if (mounted.current) setLoaded(prev => ({ ...prev, [target.id]: result }));
        return result;
      });
    return cache.current[target.id];
  }, []);

  // Only authorized sources reach the Player: the active episode plus the next drama's first episode as
  // the AUTO preload window.
  const feedDrama = useMemo<Drama>(() => ({
    id: FEED_ID, title: 'For You', subtitle: '', category: 'Popular', cover: '', episodeCount: count,
    episodes: active ? [active, ...(nextSource && nextSource !== 'unavailable' && nextSource.id !== active.id
      ? [nextSource] : [])] : [],
  }), [active, nextSource, count]);
  const player = useMinisPlayer(feedDrama, active);

  // Feed plays never move a viewer's real place backwards: only dramas with no saved progress get one.
  const saved = progress[drama.id];
  const trackProgress = active && active.id === `${drama.id}:1` && saved === null ? active : undefined;
  useWatchProgress(drama.id, trackProgress, player.currentTime, player.duration, player.isFirstFrameReady,
    player.isSwitching, null, player.seekTo);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; if (timer.current) window.clearTimeout(timer.current); };
  }, []);

  /** Moves to the nearest playable drama in `step` direction. Resolves the index committed, or undefined. */
  const advance = useCallback(async (from: number, step: 1 | -1): Promise<number | undefined> => {
    if (busyRef.current) return undefined;
    busyRef.current = true; setBusy(true);
    try {
      for (let hop = 1; hop <= count; hop++) {
        const target = wrap(from + step * hop);
        const source = await resolve(dramas[target]);
        if (!mounted.current) return undefined;
        if (source === 'unavailable') continue;
        const ok = active ? await player.switchEpisode(source) : true;
        if (!ok || !mounted.current) return undefined;
        setActive(source);
        return target;
      }
      return undefined;
    } finally {
      busyRef.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [active, count, dramas, player, resolve, wrap]);

  // Start on the first playable drama.
  useEffect(() => {
    let alive = true;
    void (async () => {
      const first = await resolve(dramas[0]);
      if (!alive) return;
      if (first !== 'unavailable') { setActive(first); return; }
      const target = await advance(0, 1);
      if (!alive) return;
      if (target === undefined) setAllUnavailable(true); else setIndex(target);
    })();
    return () => { alive = false; };
  }, []); // Mount only: `dramas` is fixed for this component's lifetime (keyed by the list load).

  // Warm the next drama's first episode and this drama's saved place (for the Continue target).
  useEffect(() => {
    if (nextDrama) void resolve(nextDrama);
    if (drama.id in progress) return;
    let alive = true;
    getProgress(drama.id).then(value => { if (alive) setProgress(prev => ({ ...prev, [drama.id]: value })); })
      .catch(() => undefined);
    return () => { alive = false; };
  }, [drama.id, nextDrama, progress, resolve]);

  const stageHeight = () => stageRef.current?.getBoundingClientRect().height ?? window.innerHeight;
  const go = (step: 1 | -1) => {
    if (count < 2) { setSettling(true); setDragOffset(0); timer.current = window.setTimeout(() => setSettling(false), SWIPE_MS); return; }
    const pending = advance(index, step);
    setSettling(true);
    setDragOffset(step === 1 ? -stageHeight() : stageHeight());
    timer.current = window.setTimeout(async () => {
      const target = await pending;
      if (!mounted.current) return;
      dragRef.current = 0;
      if (target !== undefined) { setIndex(target); setSettling(false); setDragOffset(0); return; }
      setDragOffset(0);
      timer.current = window.setTimeout(() => setSettling(false), SWIPE_MS);
    }, SWIPE_MS);
  };

  // Finishing an episode keeps the feed moving; a single-drama feed just replays.
  const handledEnded = useRef(0);
  useEffect(() => {
    if (player.endedCount <= handledEnded.current) return;
    handledEnded.current = player.endedCount;
    if (count > 1) go(1);
    else if (player.seekTo(0)) player.resumePlayback();
  }, [player.endedCount]); // React to each new "ended" only; go() reads current state from this render.

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (settling || busy) return;
      if (event.key === 'ArrowDown') go(1);
      if (event.key === 'ArrowUp') go(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const total = drama.episodeCount;
  const continueSeq = saved && saved.last_seq > 1 ? saved.last_seq : Math.min(2, total);
  const continueTo = total > 1
    ? `/playlet/theater?id=${encodeURIComponent(drama.id)}&seq=${continueSeq}`
    : `/playlet/detail?id=${encodeURIComponent(drama.id)}`;
  const current = loaded[drama.id];
  const poster = (current && current !== 'unavailable' ? current.poster : undefined) || drama.cover;
  const coverOf = (d?: DramaSummary) => {
    const source = d && loaded[d.id];
    return (source && source !== 'unavailable' ? source.poster : undefined) || d?.cover;
  };
  const edge = (d?: DramaSummary) => coverOf(d) ? <img src={coverOf(d)} alt="" /> : <div className="edge-slide" />;

  return (
    <main className="app-shell feed-page"
      onTouchStartCapture={event => {
        if (settling || busy || (event.target as HTMLElement).closest('a, button, .xgplayer-progress, .xgplayer-controls')) return;
        touchStart.current = event.touches[0]?.clientY; dragRef.current = 0;
      }}
      onTouchMoveCapture={event => {
        if (touchStart.current == null || settling || busy) return;
        const y = event.touches[0]?.clientY;
        if (y == null) return;
        let offset = y - touchStart.current;
        if (count < 2) offset *= 0.22;
        dragRef.current = offset; setDragOffset(offset);
      }}
      onTouchEndCapture={() => {
        if (touchStart.current == null) return;
        touchStart.current = undefined;
        const offset = dragRef.current;
        if (Math.abs(offset) < Math.min(120, stageHeight() * 0.16)) {
          setSettling(true); setDragOffset(0); dragRef.current = 0;
          timer.current = window.setTimeout(() => setSettling(false), SWIPE_MS);
        } else go(offset < 0 ? 1 : -1);
      }}
      onTouchCancelCapture={() => {
        touchStart.current = undefined; dragRef.current = 0; setDragOffset(0);
      }}>
      <section className="theater-stage" ref={stageRef}>
        <div className={`episode-track${settling ? ' is-settling' : ''}`}
          style={{ transform: `translate3d(0, calc(-1 * var(--theater-stage-height) + ${dragOffset}px), 0)` }}>
          <div className="episode-slide adjacent-slide">{edge(prevDrama)}</div>
          <div className="episode-slide current-slide">
            {poster && <img className={`theater-poster${player.isFirstFrameReady && active?.id === `${drama.id}:1`
              ? ' is-frame-ready' : ''}`} src={poster} alt="" />}
            <div className={`player-root${player.isMuted ? '' : ' is-unmuted'}`} ref={player.rootRef} />
          </div>
          <div className="episode-slide adjacent-slide">{edge(nextDrama)}</div>
        </div>
        <p className="feed-heading">For You</p>
        {allUnavailable && <div className="player-notice" role="alert"><strong>Nothing to play yet</strong>
          <span>New dramas are on the way. Check back soon.</span></div>}
        {player.error && !allUnavailable && <div className="player-notice" role="alert"><strong>Playback unavailable</strong>
          <span>Swipe for another drama or try again.</span>
          <button onClick={player.retryPlayback}>Try again</button></div>}
        <section className="theater-copy feed-copy">
          <Link className="eyebrow" to={`/playlet/detail?id=${encodeURIComponent(drama.id)}`}>{drama.title}</Link>
          <p>Episode 1 / {total}{drama.subtitle ? ` · ${drama.subtitle}` : ''}</p>
        </section>
        <Link className="episode-bar feed-continue" to={continueTo}>
          <DramaIcon className="episode-bar-icon" />
          <span>{total > 1 ? `Continue to Episode ${continueSeq}` : 'View drama'} · {total} Episodes</span>
          <ChevronUpIcon className="episode-bar-chevron" />
        </Link>
      </section>
      <BottomNav />
    </main>
  );
}
