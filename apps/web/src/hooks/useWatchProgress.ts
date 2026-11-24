import { useEffect, useRef, useState } from 'react';
import { saveProgress, type Progress } from '../api/account';
import type { EpisodeSource } from '../types/drama';

/** Writes only committed playback, throttled to 10s, and flushes on switch/background/exit. */
export function useWatchProgress(dramaId: string, episode: EpisodeSource | undefined, time: number,
  duration: number, ready: boolean, switching: boolean, saved: Progress | null,
  seekTo: (seconds: number) => boolean) {
  const [saveError, setSaveError] = useState(false);
  const snapshot = useRef<{ seq: number; seconds: number } | null>(null);
  const resumed = useRef<string | null>(null), alive = useRef(true), lastSaved = useRef('');
  useEffect(() => {
    alive.current = true;
    const flush = () => {
      const value = snapshot.current;
      if (!value) return;
      const key = `${value.seq}:${value.seconds}`;
      if (key === lastSaved.current) return;
      lastSaved.current = key;
      void saveProgress(dramaId, value.seq, value.seconds).then(() => {
        if (alive.current) setSaveError(false);
      }).catch(() => {
        if (lastSaved.current === key) lastSaved.current = '';
        if (alive.current) setSaveError(true);
      });
    };
    const hidden = () => { if (document.visibilityState === 'hidden') flush(); };
    const timer = window.setInterval(flush, 10_000);
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('pagehide', flush);
    return () => {
      flush(); alive.current = false; snapshot.current = null;
      window.clearInterval(timer); document.removeEventListener('visibilitychange', hidden);
      window.removeEventListener('pagehide', flush);
    };
  }, [dramaId, episode?.id]);
  useEffect(() => {
    if (!episode || !ready || switching) return;
    if (resumed.current !== episode.id) {
      if (saved?.last_seq === episode.episodeNumber && saved.position_seconds > 0) {
        if (!duration || !seekTo(Math.min(saved.position_seconds, Math.max(0, duration - 1)))) return;
      }
      resumed.current = episode.id;
      // Wait for the next actual time update after a resume seek before persisting.
      if (saved?.last_seq === episode.episodeNumber && saved.position_seconds > 0) return;
    }
    if (Number.isFinite(time)) snapshot.current = { seq: episode.episodeNumber, seconds: Math.max(0, Math.floor(time)) };
  }, [episode, time, duration, ready, switching, saved, seekTo]);
  return saveError;
}
