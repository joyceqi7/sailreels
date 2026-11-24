import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { EpisodeSheet } from '../components/EpisodeSheet';
import { BookmarkIcon, ChevronUpIcon, CommentIcon, DramaIcon, HeartIcon, ShareIcon } from '../components/Icons';
import { useDramaDetail } from '../hooks/useDramaApi';
import { useMinisPlayer } from '../hooks/useMinisPlayer';
import type { Drama, EpisodeSource } from '../types/drama';
import type { CatalogDramaDetail } from '../api/catalog-adapters';
import { getEpisodeAccess, getEpisodeList } from '../api/catalog';
import { resolveEpisodeAccess } from '../api/access';
import { UnlockSheet, type UnlockReason } from '../components/UnlockSheet';
import { getProgress, type Progress } from '../api/account';
import { useWatchProgress } from '../hooks/useWatchProgress';

export function TheaterPage() {
  const [searchParams] = useSearchParams();
  const dramaId = searchParams.get('id') ?? '';
  const requestedSeq = searchParams.get('seq');
  const [progress, setProgress] = useState<{ id: string; value: Progress | null }>();
  const [progressError, setProgressError] = useState(false);
  const { data: drama, loading, error } = useDramaDetail(dramaId);
  useEffect(() => {
    let active = true; setProgressError(false);
    void getProgress(dramaId).then(value => { if (active) setProgress({ id: dramaId, value }); })
      .catch(() => { if (active) { setProgress({ id: dramaId, value: null }); setProgressError(true); } });
    return () => { active = false; };
  }, [dramaId]);
  const initialSeq = Number(requestedSeq ?? (progress?.id === dramaId ? progress.value?.last_seq ?? 1 : 1));

  if (loading) return <main className="app-shell theater-page"><div className="page-state">Loading episodes…</div></main>;
  if (error || !drama) return <main className="app-shell theater-page"><div className="page-state">{error ?? 'Drama not found.'}</div></main>;
  if (!drama.episodes.length) return <main className="app-shell theater-page"><div className="page-state">No episodes available.</div></main>;
  if (progress?.id !== dramaId) return <main className="app-shell theater-page"><div className="page-state">Restoring your place…</div></main>;

  if (!Number.isSafeInteger(initialSeq) || initialSeq < 1 || initialSeq > drama.episodes.length) {
    return <main className="app-shell theater-page"><div className="page-state">Episode not found. <Link to="/playlet/square">Browse dramas</Link></div></main>;
  }
  return <TheaterContent key={`${drama.id}:${initialSeq}`} drama={drama} initialSeq={initialSeq}
    saved={progress.value} progressError={progressError} />;
}

function TheaterContent({ drama, initialSeq, saved, progressError }: {
  drama: CatalogDramaDetail; initialSeq: number; saved: Progress | null; progressError: boolean;
}) {
  const [episodeIndex, setEpisodeIndex] = useState(initialSeq - 1);
  const [activeEpisode, setActiveEpisode] = useState<EpisodeSource>();
  const [checkingAccess, setCheckingAccess] = useState(true);
  const [accessError, setAccessError] = useState('');
  const [unlockRequest, setUnlockRequest] = useState<{ index: number; reason: UnlockReason }>();
  const [locked, setLocked] = useState(() => new Set(drama.episodes
    .filter(e => e.episodeNumber > drama.freeEpisodes).map(e => e.episodeNumber)));
  const checkingRef = useRef(false);
  const mountedRef = useRef(true);
  const resumeAfterUnlock = useRef(false);
  const [preloadWindow, setPreloadWindow] = useState<EpisodeSource[]>([]);
  // Only authorized sources enter the Player/preload boundary; metadata never does.
  const playbackDrama = useMemo<Drama>(() => ({ ...drama, episodes: activeEpisode
    ? [activeEpisode, ...preloadWindow.filter(e => e.episodeNumber > activeEpisode.episodeNumber)] : [] }),
    [drama, activeEpisode, preloadWindow]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [liked, setLiked] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const [settling, setSettling] = useState(false);
  const episode = drama.episodes[episodeIndex];
  const {
    rootRef,
    error,
    isSwitching,
    switchEpisode,
    endedCount,
    lifecyclePauseCount,
    isSeeking,
    seekTime,
    duration,
    currentTime,
    seekTo,
    isMuted,
    isFirstFrameReady,
    setPlaybackRate,
    getPlaybackRate,
    pausePlayback,
    resumePlayback,
    retryPlayback,
  } = useMinisPlayer(playbackDrama, activeEpisode);
  const saveError = useWatchProgress(drama.id, activeEpisode, currentTime, duration,
    isFirstFrameReady, isSwitching, saved, seekTo);
  useEffect(() => {
    if (!activeEpisode || !isFirstFrameReady) return;
    let active = true;
    setPreloadWindow([]);
    void (async () => {
      const sources: EpisodeSource[] = [];
      for (let seq = activeEpisode.episodeNumber + 1; seq <= Math.min(drama.episodeCount, activeEpisode.episodeNumber + 2); seq++) {
        const access = await getEpisodeAccess(drama.id, seq);
        if (!active || access.access === 'locked') break;
        sources.push(resolveEpisodeAccess(access, drama.id, seq));
      }
      if (active) setPreloadWindow(sources);
    })().catch(() => { /* Preload failure must never block the active episode. */ });
    return () => { active = false; };
  }, [drama.id, drama.episodeCount, activeEpisode, isFirstFrameReady]);
  const [speeding, setSpeeding] = useState(false);
  const [speedPressing, setSpeedPressing] = useState(false);
  const [speedLocked, setSpeedLocked] = useState(false);
  const [lockReady, setLockReady] = useState(false);
  const [speedDragY, setSpeedDragY] = useState(0);
  const [showExitSpeedToast, setShowExitSpeedToast] = useState(false);
  const [showDramaEndedToast, setShowDramaEndedToast] = useState(false);
  const [pressPoint, setPressPoint] = useState({ x: 0, y: 0 });
  const stageRef = useRef<HTMLElement>(null);
  const touchStart = useRef<number | undefined>(undefined);
  const touchStartX = useRef<number | undefined>(undefined);
  const dragOffsetRef = useRef(0);
  const pendingDragOffset = useRef(0);
  const dragFrame = useRef<number | undefined>(undefined);
  const switchTimer = useRef<number | undefined>(undefined);
  const longPressTimer = useRef<number | undefined>(undefined);
  const exitToastTimer = useRef<number | undefined>(undefined);
  const speedingRef = useRef(false);
  const speedPressingRef = useRef(false);
  const speedLockedRef = useRef(false);
  const lockReadyRef = useRef(false);
  const previousPlaybackRate = useRef(1);

  const previousEpisode = drama.episodes[episodeIndex - 1];
  const nextEpisode = drama.episodes[episodeIndex + 1];
  const getStageHeight = () => stageRef.current?.getBoundingClientRect().height ?? window.innerHeight;
  const trackTransform = `translate3d(0, calc(-1 * var(--theater-stage-height) + ${dragOffset}px), 0)`;
  const scheduleDragOffset = (offset: number) => {
    pendingDragOffset.current = offset;
    if (dragFrame.current) return;
    dragFrame.current = window.requestAnimationFrame(() => {
      setDragOffset(pendingDragOffset.current);
      dragFrame.current = undefined;
    });
  };
  const cancelDragFrame = () => {
    if (dragFrame.current) window.cancelAnimationFrame(dragFrame.current);
    dragFrame.current = undefined;
  };
  const formatTime = (seconds: number) => {
    const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
    const minutes = Math.floor(safeSeconds / 60);
    return `${minutes}:${String(safeSeconds % 60).padStart(2, '0')}`;
  };

  const stopLongPressTimer = () => {
    if (longPressTimer.current) {
      window.clearTimeout(longPressTimer.current);
      longPressTimer.current = undefined;
    }
  };

  const leaveSpeedMode = useCallback((showExitToast = false, restoreRate = previousPlaybackRate.current) => {
    setPlaybackRate(restoreRate);
    speedingRef.current = false;
    speedPressingRef.current = false;
    speedLockedRef.current = false;
    lockReadyRef.current = false;
    setSpeeding(false);
    setSpeedPressing(false);
    setSpeedLocked(false);
    setLockReady(false);
    setSpeedDragY(0);
    if (showExitToast) {
      setShowExitSpeedToast(true);
      if (exitToastTimer.current) window.clearTimeout(exitToastTimer.current);
      exitToastTimer.current = window.setTimeout(() => setShowExitSpeedToast(false), 1600);
    }
  }, [setPlaybackRate]);

  useEffect(() => {
    mountedRef.current = true;
    getEpisodeAccess(drama.id, initialSeq).then(result => {
      if (!mountedRef.current) return;
      if (result.access === 'locked') setUnlockRequest({ index: initialSeq - 1, reason: 'entry' });
      else setActiveEpisode(resolveEpisodeAccess(result, drama.id, initialSeq));
    }).catch(() => {
      if (mountedRef.current) setAccessError('Unable to check viewing access. Please try again.');
    }).finally(() => { if (mountedRef.current) setCheckingAccess(false); });
    getEpisodeList(drama.id).then(result => {
      if (mountedRef.current) setLocked(new Set(result.episodes.filter(e => e.locked).map(e => e.seq)));
    }).catch(() => undefined);
    return () => { mountedRef.current = false; };
  }, [drama.id, initialSeq]);

  const commitEpisode = async (targetIndex: number, source: EpisodeSource): Promise<boolean> => {
    const success = activeEpisode ? await switchEpisode(source) : true;
    if (success && mountedRef.current) {
      setActiveEpisode(source);
      setLocked(previous => { const next = new Set(previous); next.delete(source.episodeNumber); return next; });
    }
    return success;
  };

  const requestEpisode = async (targetIndex: number, reason: UnlockReason = 'jump'): Promise<boolean> => {
    if (
      targetIndex < 0 ||
      targetIndex >= drama.episodes.length ||
      isSwitching || checkingAccess || checkingRef.current || unlockRequest
    ) {
      return false;
    }
    if (targetIndex === episodeIndex && activeEpisode && !error && !accessError) return true;

    previousPlaybackRate.current = 1;
    leaveSpeedMode(false, 1);
    setShowDramaEndedToast(false);
    checkingRef.current = true;
    setCheckingAccess(true); setAccessError('');
    try {
      const result = await getEpisodeAccess(drama.id, targetIndex + 1);
      if (!mountedRef.current) return false;
      if (result.access === 'locked') {
        resumeAfterUnlock.current = pausePlayback();
        setLocked(previous => new Set(previous).add(targetIndex + 1));
        setUnlockRequest({ index: targetIndex, reason });
        return false;
      }
      const source = resolveEpisodeAccess(result, drama.id, targetIndex + 1);
      if (targetIndex === episodeIndex && error) {
        setActiveEpisode(source); retryPlayback(); return true;
      }
      return await commitEpisode(targetIndex, source);
    } catch {
      if (mountedRef.current) setAccessError('Unable to check this episode. Please try again.');
      return false;
    } finally {
      checkingRef.current = false;
      if (mountedRef.current) setCheckingAccess(false);
    }
  };

  const selectEpisode = async (targetIndex: number, reason: UnlockReason = 'jump'): Promise<boolean> => {
    const success = await requestEpisode(targetIndex, reason);
    if (success) setEpisodeIndex(targetIndex);
    return success;
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (sheetOpen || unlockRequest || (event.target instanceof HTMLElement && event.target.closest('[role="dialog"]'))) return;
      if (event.key === 'ArrowUp') void selectEpisode(episodeIndex - 1);
      if (event.key === 'ArrowDown') void selectEpisode(episodeIndex + 1);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [episodeIndex, selectEpisode]);

  // Timers belong to the mounted theater, not to the keyboard listener.
  // Clearing them on every selectEpisode identity change can cancel an active
  // swipe transaction after isSwitching updates and leave settling stuck true.
  useEffect(() => {
    // XGPlayer may stop touchend/touchcancel propagation after a tap on its
    // media layer. Capture at window level so a pending long-press timer can
    // never survive an ordinary tap.
    const cancelPendingLongPress = () => stopLongPressTimer();
    window.addEventListener('touchend', cancelPendingLongPress, true);
    window.addEventListener('touchcancel', cancelPendingLongPress, true);
    return () => {
      window.removeEventListener('touchend', cancelPendingLongPress, true);
      window.removeEventListener('touchcancel', cancelPendingLongPress, true);
      if (switchTimer.current) window.clearTimeout(switchTimer.current);
      if (longPressTimer.current) window.clearTimeout(longPressTimer.current);
      if (exitToastTimer.current) window.clearTimeout(exitToastTimer.current);
      if (dragFrame.current) window.cancelAnimationFrame(dragFrame.current);
    };
  }, []);

  const handledEndedCount = useRef(0);
  useEffect(() => {
    if (endedCount <= handledEndedCount.current) return;
    handledEndedCount.current = endedCount;
    if (episodeIndex < drama.episodes.length - 1) {
      void selectEpisode(episodeIndex + 1, 'ended');
    } else {
      setShowDramaEndedToast(true);
    }
  }, [drama.episodes.length, endedCount, episodeIndex, selectEpisode]);

  const handledLifecyclePauseCount = useRef(0);
  useEffect(() => {
    if (lifecyclePauseCount <= handledLifecyclePauseCount.current) return;
    handledLifecyclePauseCount.current = lifecyclePauseCount;
    previousPlaybackRate.current = 1;
    speedingRef.current = false;
    speedPressingRef.current = false;
    speedLockedRef.current = false;
    lockReadyRef.current = false;
    setSpeeding(false);
    setSpeedPressing(false);
    setSpeedLocked(false);
    setLockReady(false);
    setSpeedDragY(0);
  }, [lifecyclePauseCount]);

  const finishDrag = (direction: -1 | 0 | 1) => {
    cancelDragFrame();
    const canMove =
      (direction === -1 && episodeIndex < drama.episodes.length - 1) ||
      (direction === 1 && episodeIndex > 0);
    if (!canMove) {
      setSettling(true);
      dragOffsetRef.current = 0;
      setDragOffset(0);
      switchTimer.current = window.setTimeout(() => setSettling(false), 260);
      return;
    }

    const stageHeight = getStageHeight();
    const targetIndex = episodeIndex + (direction === -1 ? 1 : -1);
    const switchPromise = requestEpisode(targetIndex);
    setSettling(true);
    setDragOffset(direction === -1 ? -stageHeight : stageHeight);
    switchTimer.current = window.setTimeout(async () => {
      const success = await switchPromise;
      dragOffsetRef.current = 0;
      if (success) {
        setEpisodeIndex(targetIndex);
        setSettling(false);
        setDragOffset(0);
        return;
      }

      // Player remains on the committed episode; animate its card back in.
      setDragOffset(0);
      switchTimer.current = window.setTimeout(() => setSettling(false), 260);
    }, 260);
  };
  return (
    <main
      className={`app-shell theater-page${speeding ? ' is-speeding' : ''}`}
      onContextMenu={(event) => event.preventDefault()}
      onTouchStartCapture={(event) => {
        if (settling || isSwitching || sheetOpen || checkingAccess || unlockRequest) return;
        if ((event.target as HTMLElement).closest('button, .xgplayer-progress, .xgplayer-controls')) return;
        const touch = event.touches[0];
        if (!touch) return;
        touchStart.current = touch.clientY;
        touchStartX.current = touch.clientX;
        dragOffsetRef.current = 0;
        const stageRect = stageRef.current?.getBoundingClientRect();
        setPressPoint({
          x: touch.clientX - (stageRect?.left ?? 0),
          y: touch.clientY - (stageRect?.top ?? 0),
        });
        stopLongPressTimer();
        longPressTimer.current = window.setTimeout(() => {
          longPressTimer.current = undefined;
          if (!speedLockedRef.current) {
            previousPlaybackRate.current = getPlaybackRate();
            setPlaybackRate(2);
          }
          speedingRef.current = true;
          speedPressingRef.current = true;
          lockReadyRef.current = false;
          setSpeeding(true);
          setSpeedPressing(true);
          setLockReady(false);
          setSpeedDragY(0);
        }, 420);
      }}
      onTouchMoveCapture={(event) => {
        if (settling || isSwitching || sheetOpen || checkingAccess || unlockRequest || touchStart.current == null) return;
        if ((event.target as HTMLElement).closest('.xgplayer-progress, .xgplayer-controls')) return;
        const touch = event.touches[0];
        const currentY = touch?.clientY;
        if (currentY == null || touchStartX.current == null) return;
        let offset = currentY - touchStart.current;
        const offsetX = touch.clientX - touchStartX.current;
        if (speedPressingRef.current) {
          const nextReady = offset > 72;
          setSpeedDragY(Math.max(0, Math.min(offset, 132)));
          if (nextReady !== lockReadyRef.current) {
            lockReadyRef.current = nextReady;
            setLockReady(nextReady);
            if (nextReady) navigator.vibrate?.(18);
          }
          return;
        }
        if (Math.abs(offset) > 12 || Math.abs(offsetX) > 12) stopLongPressTimer();
        if ((episodeIndex === 0 && offset > 0) || (episodeIndex === drama.episodes.length - 1 && offset < 0)) {
          offset *= 0.22;
        }
        dragOffsetRef.current = offset;
        scheduleDragOffset(offset);
      }}
      onTouchCancelCapture={() => {
        stopLongPressTimer();
        touchStart.current = undefined;
        touchStartX.current = undefined;
        if (speedPressingRef.current && !speedLockedRef.current) leaveSpeedMode();
        else if (speedPressingRef.current) {
          speedPressingRef.current = false;
          setSpeedPressing(false);
          setLockReady(false);
          setSpeedDragY(0);
        }
        finishDrag(0);
      }}
      onTouchEndCapture={(event) => {
        stopLongPressTimer();
        const start = touchStart.current;
        touchStart.current = undefined;
        touchStartX.current = undefined;
        if (speedPressingRef.current) {
          event.preventDefault();
          if (lockReadyRef.current) {
            if (speedLockedRef.current) {
              leaveSpeedMode(true);
            } else {
              speedLockedRef.current = true;
              speedPressingRef.current = false;
              lockReadyRef.current = false;
              setSpeedLocked(true);
              setSpeedPressing(false);
              setLockReady(false);
              setSpeedDragY(0);
            }
          } else if (!speedLockedRef.current) {
            leaveSpeedMode();
          } else {
            speedPressingRef.current = false;
            setSpeedPressing(false);
            setLockReady(false);
            setSpeedDragY(0);
          }
          return;
        }
        if (start == null) return;
        const threshold = Math.min(120, getStageHeight() * 0.16);
        const finalOffset = dragOffsetRef.current;
        if (Math.abs(finalOffset) < threshold) finishDrag(0);
        else finishDrag(finalOffset < 0 ? -1 : 1);
      }}
    >
      <section className={`theater-stage${isSeeking ? ' is-seeking' : ''}${speedPressing ? ' is-speeding' : ''}`} ref={stageRef}>
        <div
          className={`episode-track${settling ? ' is-settling' : ''}${dragOffset !== 0 ? ' is-dragging' : ''}`}
          style={{ transform: trackTransform }}
        >
          <div className="episode-slide adjacent-slide">
            {previousEpisode?.poster ? <img src={previousEpisode.poster} alt="" /> : <div className="edge-slide" />}
          </div>
          <div className="episode-slide current-slide">
            {episode.poster || drama.cover ? (
              <img
                className={`theater-poster${isFirstFrameReady ? ' is-frame-ready' : ''}`}
                src={episode.poster || drama.cover}
                alt=""
              />
            ) : null}
            <div
              className={`player-root${isMuted ? '' : ' is-unmuted'}`}
              ref={rootRef}
            />
            {/* <div className="theater-gradient" /> */}
          </div>
          <div className="episode-slide adjacent-slide">
            {nextEpisode?.poster ? <img src={nextEpisode.poster} alt="" /> : <div className="edge-slide" />}
          </div>
        </div>
        <Link className="theater-back" to={`/playlet/detail?id=${encodeURIComponent(drama.id)}`} aria-label="Back to drama details">‹</Link>
        {(saveError || progressError) && <p className="progress-notice" role="status">Your place could not be saved or restored. Playback is still available.</p>}
        {checkingAccess && <div className="player-notice" role="status">Checking viewing access…</div>}
        {(error || accessError) && <div className="player-notice" role="alert"><strong>Playback unavailable</strong>
          <span>{accessError || 'Open this drama in TikTok or try again.'}</span>
          <button onClick={() => { void selectEpisode(episodeIndex); }}>Try again</button></div>}
        <aside className="social-actions">
          <button className={liked ? 'is-liked' : ''} onClick={() => setLiked((value) => !value)}><HeartIcon /><span>{liked ? '12.1K' : '12K'}</span></button>
          <button><CommentIcon /><span>456</span></button>
          <button><BookmarkIcon /><span>68</span></button>
          <button><ShareIcon /><span>43</span></button>
        </aside>

        <section className="theater-copy">
          <p className="eyebrow">{drama.title}</p>
          <p>Episode {episodeIndex + 1} | {episode.description}</p>
        </section>
        {/* {isSeeking && (
          <div className="seek-time" aria-live="polite">
            <strong>{formatTime(seekTime)}</strong><span>/</span><b>{formatTime(duration)}</b>
          </div>
        )} */}
        <div className="seek-time" aria-live="polite">
            <strong>{formatTime(seekTime)}</strong><span>/</span><b>{formatTime(duration)}</b>
          </div>
        {speedLocked && !speedPressing && (
          <div className="speed-locked-toast" role="status">
            <img className="speed-status-icon" src="/static/lock.svg" alt="" />
            <span>Locked at 2× speed</span>
          </div>
        )}
        {showExitSpeedToast && (
          <div className="speed-exit-toast" role="status">
            <img className="speed-status-icon" src="/static/lock.svg" alt="" />
            <span>Exit 2× speed</span>
          </div>
        )}
        {showDramaEndedToast && (
          <div className="drama-ended-toast" role="status">You’ve finished the drama</div>
        )}
        {speedPressing && (
          <>
            {speedDragY > 0 && (
              <div
                className={`speed-lock-track${lockReady ? ' is-ready' : ''}`}
                style={{ left: pressPoint.x, top: pressPoint.y, height: speedDragY }}
                aria-hidden="true"
              />
            )}
            <div
              className={`speed-touch${lockReady ? ' is-ready' : ''}`}
              style={{ left: pressPoint.x, top: pressPoint.y + speedDragY }}
              aria-hidden="true"
            />
          </>
        )}
      </section>
      <footer className="theater-footer">
        {speedPressing ? (
          <div className={`speed-hint${lockReady ? ' is-ready' : ''}`}>
            <img
              className="speed-hint-icon"
              src={lockReady ? '/static/lock.svg' : '/static/speed2.svg'}
              alt=""
            />
            <span>
              {speedLocked
                ? lockReady
                  ? 'Release to exit 2× speed'
                  : 'Swipe down to exit 2× speed'
                : lockReady
                  ? 'Release to lock 2× speed'
                  : 'Swipe down to lock 2× speed'}
            </span>
          </div>
        ) : (
          <button className="episode-bar" disabled={isSwitching || checkingAccess} onClick={() => setSheetOpen(true)}>
            <DramaIcon className="episode-bar-icon" />
            <span>Drama · {drama.episodes.length} Episodes</span>
            <ChevronUpIcon className="episode-bar-chevron" />
          </button>
        )}
        {/* <div className="home-indicator" aria-hidden="true" /> */}
      </footer>

      <EpisodeSheet
        drama={drama}
        current={episodeIndex}
        locked={locked}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onSelect={(index) => {
          void selectEpisode(index);
        }}
      />
      {unlockRequest && <UnlockSheet key={`${drama.id}:${unlockRequest.index}`} dramaId={drama.id}
        seq={unlockRequest.index + 1} reason={unlockRequest.reason}
        onClose={() => {
          setUnlockRequest(undefined);
          if (resumeAfterUnlock.current) resumePlayback();
          resumeAfterUnlock.current = false;
        }} onUnlocked={async source => {
          if (!mountedRef.current) return;
          const index = unlockRequest.index;
          if (await commitEpisode(index, source)) {
            setEpisodeIndex(index); setUnlockRequest(undefined); resumeAfterUnlock.current = false;
            getEpisodeList(drama.id).then(result => {
              if (mountedRef.current) setLocked(new Set(result.episodes.filter(e => e.locked).map(e => e.seq)));
            }).catch(() => undefined);
          } else throw new Error('Playback could not start.');
        }} />}
    </main>
  );
}
