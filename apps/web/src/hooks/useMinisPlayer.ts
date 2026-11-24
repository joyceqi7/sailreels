import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createMinisDramaPlayer,
  clearDramaPreload,
  playNextEpisode,
  playerEvent,
  setupDramaAutoPreload,
  type MinisProgressDragData,
  type MinisProgressPlugin,
  type MinisPlayerInstance,
  type PlayerConfigHooks,
} from '../plugins/minis-player';
import type { Drama, EpisodeSource } from '../types/drama';

export type PlayerStatus = 'idle' | 'loading' | 'ready' | 'playing' | 'error';

function pausePlayer(player: MinisPlayerInstance | null) {
  if (player?.pause) player.pause();
  else player?.player?.pause?.();
}

async function playPlayer(player: MinisPlayerInstance | null) {
  const result = player?.play ? player.play() : player?.player?.play?.();
  await result;
}

function getProgressDragData(args: unknown[]): MinisProgressDragData | undefined {
  return args.find((value): value is MinisProgressDragData => {
    if (!value || typeof value !== 'object') return false;
    const data = value as MinisProgressDragData;
    return Number.isFinite(data.seekTime) ||
      Number.isFinite(data.currentTime) ||
      Number.isFinite(data.percent);
  });
}

function clampTime(time: number, duration: number) {
  return Math.min(Math.max(time, 0), duration || time);
}

function getProgressTargetTime(
  data: MinisProgressDragData | undefined,
  duration: number,
) {
  // seekTime is the actual media position after segmented-timeline offsets.
  if (Number.isFinite(data?.seekTime)) {
    return clampTime(Number(data?.seekTime), duration);
  }
  if (Number.isFinite(data?.currentTime)) {
    return clampTime(Number(data?.currentTime), duration);
  }
  if (Number.isFinite(data?.percent) && duration > 0) {
    return clampTime(Number(data?.percent) * duration, duration);
  }
  return undefined;
}

function readProgressTargetTime(root: HTMLElement | null, duration: number) {
  if (!root || duration <= 0) return undefined;
  const thumb = root.querySelector<HTMLElement>('.xgplayer-progress-btn');
  const percent = Number.parseFloat(thumb?.style.left ?? '');
  return Number.isFinite(percent)
    ? clampTime((percent / 100) * duration, duration)
    : undefined;
}

/**
 * Some Minis Player versions do not forward progress.onMove* consistently.
 * Bind the public progress hooks after plugin initialization as the compatible
 * path used by vod-h5-demo. Returning true preserves the default seek action.
 */
function bindProgressPluginHooks(
  player: MinisPlayerInstance,
  hooks: PlayerConfigHooks,
) {
  let boundProgress: MinisProgressPlugin | undefined;
  return () => {
    const progress =
      player.player?.getPlugin?.('progress') ??
      player.player?.plugins?.progress;
    if (!progress?.useHooks || progress === boundProgress) return;

    progress.useHooks('dragstart', (...args) => {
      hooks.onProgressMoveStart?.(getProgressDragData(args));
      return true;
    });
    progress.useHooks('drag', (...args) => {
      hooks.onProgressMove?.(getProgressDragData(args));
      return true;
    });
    progress.useHooks('dragend', (...args) => {
      hooks.onProgressMoveEnd?.(getProgressDragData(args));
      return true;
    });
    // COMPLETE may replace the plugin object. Track the actual instance so the
    // newly-created progress plugin is bound instead of being skipped.
    boundProgress = progress;
  };
}

export function useMinisPlayer(drama: Drama, initialEpisode?: EpisodeSource) {
  const rootRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<MinisPlayerInstance | null>(null);
  const disposedRef = useRef(false);
  const lifecycleGenerationRef = useRef(0);
  const activeEpisodeIdRef = useRef<string | undefined>(undefined);
  const pendingEpisodeIdRef = useRef<string | undefined>(undefined);
  const switchingRef = useRef(false);
  const progressDraggingRef = useRef(false);
  const seekPreviewFrameRef = useRef<number | undefined>(undefined);
  const firstFrameRequestRef = useRef<{
    media: HTMLVideoElement;
    id: number;
  } | undefined>(undefined);
  const firstFrameFallbackRef = useRef<number | undefined>(undefined);
  const lifecycleSuspendedRef = useRef(false);
  const resumeAfterLifecycleRef = useRef(false);
  const [status, setStatus] = useState<PlayerStatus>('idle');
  const [playerAttempt, setPlayerAttempt] = useState(0);
  const [error, setError] = useState<string>();
  const [isSwitching, setIsSwitching] = useState(false);
  const [isSeeking, setIsSeeking] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [seekPreviewTime, setSeekPreviewTime] = useState<number>();
  const [duration, setDuration] = useState(0);
  const [isMuted, setIsMuted] = useState(true);
  const [endedCount, setEndedCount] = useState(0);
  const [lifecyclePauseCount, setLifecyclePauseCount] = useState(0);
  const [firstFrameEpisodeId, setFirstFrameEpisodeId] = useState<string>();

  const cancelFirstFrameRequest = useCallback(() => {
    const request = firstFrameRequestRef.current;
    if (request) {
      request.media.cancelVideoFrameCallback?.(request.id);
      firstFrameRequestRef.current = undefined;
    }
    if (firstFrameFallbackRef.current) {
      window.cancelAnimationFrame(firstFrameFallbackRef.current);
      firstFrameFallbackRef.current = undefined;
    }
  }, []);

  const markFirstFrameAfterPresentation = useCallback((episodeId?: string) => {
    if (!episodeId) return;
    cancelFirstFrameRequest();

    const commit = () => {
      firstFrameRequestRef.current = undefined;
      firstFrameFallbackRef.current = undefined;
      if (disposedRef.current) return;
      const currentEpisodeId =
        pendingEpisodeIdRef.current ?? activeEpisodeIdRef.current;
      if (currentEpisodeId === episodeId) setFirstFrameEpisodeId(episodeId);
    };
    const media = playerRef.current?.player?.media;
    if (media?.requestVideoFrameCallback) {
      const id = media.requestVideoFrameCallback(commit);
      firstFrameRequestRef.current = { media, id };
      return;
    }

    // Fallback for older WebViews: PLAYING means a frame is available; keep
    // the poster through the next rendering opportunity before revealing it.
    firstFrameFallbackRef.current = window.requestAnimationFrame(commit);
  }, [cancelFirstFrameRequest]);

  const syncTime = useCallback(() => {
    if (disposedRef.current) return;
    const media = playerRef.current?.player?.media;
    const mediaDuration = Number.isFinite(media?.duration) ? Number(media?.duration) : 0;
    setCurrentTime(Number(media?.currentTime || 0));
    setDuration(mediaDuration);
  }, []);

  const syncSeekPreview = useCallback((
    data?: MinisProgressDragData,
    fallbackToMedia = false,
  ) => {
    if (disposedRef.current) return;
    const media = playerRef.current?.player?.media;
    const mediaDuration = Number.isFinite(media?.duration) ? Number(media?.duration) : 0;
    const targetTime = getProgressTargetTime(data, mediaDuration);

    if (seekPreviewFrameRef.current) {
      window.cancelAnimationFrame(seekPreviewFrameRef.current);
      seekPreviewFrameRef.current = undefined;
    }
    if (targetTime !== undefined) {
      setSeekPreviewTime(targetTime);
      return;
    }
    if (fallbackToMedia) {
      setSeekPreviewTime(Number(media?.currentTime || 0));
    }

    // Older Minis builds may not forward drag data. Read the thumb only after
    // the Player's default drag handler has updated its position.
    seekPreviewFrameRef.current = window.requestAnimationFrame(() => {
      seekPreviewFrameRef.current = undefined;
      if (disposedRef.current || !progressDraggingRef.current) return;
      const fallbackTime = readProgressTargetTime(rootRef.current, mediaDuration);
      if (fallbackTime !== undefined) setSeekPreviewTime(fallbackTime);
    });
  }, []);

  const progressHooks = useCallback(() => ({
    onProgressMoveStart: (data?: MinisProgressDragData) => {
      if (disposedRef.current) return;
      progressDraggingRef.current = true;
      playerRef.current?.player?.plugins?.progress?.focus?.();
      setIsSeeking(true);
      syncSeekPreview(data, true);
    },
    onProgressMove: (data?: MinisProgressDragData) => {
      // Some Player builds run the hook after applying the seek but do not
      // forward drag data. In that case media.currentTime is already the new
      // position and is a better fallback than the press-start time.
      syncSeekPreview(data, true);
    },
    onProgressMoveEnd: (data?: MinisProgressDragData) => {
      if (disposedRef.current) return;
      syncSeekPreview(data);
      progressDraggingRef.current = false;
      playerRef.current?.player?.plugins?.progress?.blur?.();
      setIsSeeking(false);
      setSeekPreviewTime(undefined);
    },
  }), [syncSeekPreview]);

  /**
   * Transactional episode switch. The caller commits its episode UI only when
   * this resolves true; failures keep activeEpisodeIdRef on the previous item.
   */
  const switchEpisode = useCallback(async (target: EpisodeSource): Promise<boolean> => {
    const player = playerRef.current;
    const root = rootRef.current;
    if (!player || !root || disposedRef.current) return false;
    if (activeEpisodeIdRef.current === target.id) return true;
    if (switchingRef.current) return false;

    switchingRef.current = true;
    pendingEpisodeIdRef.current = target.id;
    cancelFirstFrameRequest();
    setIsSwitching(true);
    setStatus('loading');
    setError(undefined);
    progressDraggingRef.current = false;
    setIsSeeking(false);
    setCurrentTime(0);
    setSeekPreviewTime(undefined);
    setDuration(0);

    try {
      await playNextEpisode(player, root, drama, target, progressHooks());
      if (disposedRef.current) return false;

      activeEpisodeIdRef.current = target.id;
      pendingEpisodeIdRef.current = undefined;
      if (lifecycleSuspendedRef.current || document.visibilityState === 'hidden') {
        resumeAfterLifecycleRef.current = true;
        pausePlayer(player);
      }
      return true;
    } catch (cause) {
      if (!disposedRef.current) {
        setStatus('error');
        setError(cause instanceof Error ? cause.message : 'playNext() failed.');
        if (!lifecycleSuspendedRef.current) {
          void playPlayer(player).catch(() => undefined);
        }
      }
      return false;
    } finally {
      pendingEpisodeIdRef.current = undefined;
      switchingRef.current = false;
      if (!disposedRef.current) setIsSwitching(false);
    }
  }, [cancelFirstFrameRequest, drama, progressHooks]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !initialEpisode) return;
    const generation = ++lifecycleGenerationRef.current;
    let ownedPlayer: MinisPlayerInstance | null = null;
    let removeMutedListener: () => void = () => undefined;
    let mutedSyncFrame: number | undefined;
    let autoPreloadConfigured = false;
    const isStale = () =>
      disposedRef.current || generation !== lifecycleGenerationRef.current;
    const configureAutoPreloadAfterFirstFrame = () => {
      if (autoPreloadConfigured || isStale()) return;
      autoPreloadConfigured = true;
      void setupDramaAutoPreload(drama, drama.episodes);
    };

    disposedRef.current = false;
    activeEpisodeIdRef.current = undefined;
    pendingEpisodeIdRef.current = undefined;
    cancelFirstFrameRequest();
    setStatus('loading');
    setError(undefined);
    progressDraggingRef.current = false;
    setIsSeeking(false);
    setCurrentTime(0);
    setSeekPreviewTime(undefined);
    setDuration(0);
    setFirstFrameEpisodeId(undefined);

    // Optional preload must never hold the first authorized frame hostage.
    // Configure AUTO after PLAYING for both direct and discovery entries.
    const playerProgressHooks = progressHooks();
    createMinisDramaPlayer(root, drama, initialEpisode, playerProgressHooks)
      .then(({ Player, player }) => {
        if (isStale()) {
          player.destroy?.();
          return;
        }
        ownedPlayer = player;
        playerRef.current = player;
        activeEpisodeIdRef.current = initialEpisode.id;
        const media = player.player?.media;
        const syncMuted = () => {
          setIsMuted(Boolean(playerRef.current?.player?.media?.muted));
        };
        const syncMutedAfterUnmuteClick = (event: MouseEvent) => {
          const target = event.target;
          if (!(target instanceof Element) || !target.closest('.xgplayer-unmute')) return;
          if (mutedSyncFrame) window.cancelAnimationFrame(mutedSyncFrame);
          mutedSyncFrame = window.requestAnimationFrame(() => {
            mutedSyncFrame = undefined;
            syncMuted();
          });
        };
        // The Player plugin stops bubbling after handling the click, so observe
        // it in capture phase and read the final media state on the next frame.
        root.addEventListener('click', syncMutedAfterUnmuteClick, true);
        if (media) {
          media.addEventListener('volumechange', syncMuted);
          syncMuted();
        }
        removeMutedListener = () => {
          root.removeEventListener('click', syncMutedAfterUnmuteClick, true);
          media?.removeEventListener('volumechange', syncMuted);
          if (mutedSyncFrame) window.cancelAnimationFrame(mutedSyncFrame);
        };
        const bindProgressHooks = bindProgressPluginHooks(player, playerProgressHooks);
        bindProgressHooks();
        player.once?.(
          playerEvent(Player, 'COMPLETE', 'complete'),
          bindProgressHooks,
        );

        player.on?.(playerEvent(Player, 'READY', 'ready'), () => {
          if (!disposedRef.current) setStatus('ready');
        });
        player.on?.(playerEvent(Player, 'LOAD_START', 'loadstart'), () => {
          if (disposedRef.current) return;
          setStatus('loading');
        });
        player.on?.(playerEvent(Player, 'PLAYING', 'playing'), () => {
          if (disposedRef.current) return;
          setStatus('playing');
          setIsMuted(Boolean(playerRef.current?.player?.media?.muted));
          markFirstFrameAfterPresentation(
            pendingEpisodeIdRef.current ?? activeEpisodeIdRef.current,
          );
          configureAutoPreloadAfterFirstFrame();
        });
        player.on?.(playerEvent(Player, 'TIME_UPDATE', 'timeupdate'), () => {
          if (!progressDraggingRef.current) syncTime();
        });
        player.on?.(playerEvent(Player, 'DURATION_CHANGE', 'durationchange'), () => {
          syncTime();
        });
        player.on?.(playerEvent(Player, 'SEEKING', 'seeking'), () => {
          if (disposedRef.current) return;
          const mediaTime = playerRef.current?.player?.media?.currentTime;
          if (Number.isFinite(mediaTime)) setSeekPreviewTime(Number(mediaTime));
          setIsSeeking(true);
        });
        player.on?.(playerEvent(Player, 'SEEKED', 'seeked'), () => {
          if (disposedRef.current) return;
          // During a thumb drag the media element emits seeking/seeked pairs
          // for intermediate positions. Keep the clear-screen state, but do
          // use the completed media position as the seek-time preview.
          if (progressDraggingRef.current) {
            const mediaTime = playerRef.current?.player?.media?.currentTime;
            if (Number.isFinite(mediaTime)) setSeekPreviewTime(Number(mediaTime));
            return;
          }
          syncTime();
          setSeekPreviewTime(undefined);
          setIsSeeking(false);
        });
        player.on?.(playerEvent(Player, 'ENDED', 'ended'), () => {
          if (!disposedRef.current && !switchingRef.current) {
            setEndedCount((count) => count + 1);
          }
        });
        player.on?.(playerEvent(Player, 'ERROR', 'error'), (cause) => {
          if (disposedRef.current) return;
          setStatus('error');
          setError(cause instanceof Error
            ? cause.message
            : 'Playback failed. Replace the mock episode identifiers.');
        });

        if (lifecycleSuspendedRef.current || document.visibilityState === 'hidden') {
          resumeAfterLifecycleRef.current = true;
          pausePlayer(player);
        }
      })
      .catch((cause: unknown) => {
        if (isStale()) return;
        setStatus('error');
        setError(cause instanceof Error ? cause.message : String(cause));
      });

    return () => {
      if (generation === lifecycleGenerationRef.current) {
        lifecycleGenerationRef.current += 1;
        disposedRef.current = true;
      }
      switchingRef.current = false;
      progressDraggingRef.current = false;
      if (seekPreviewFrameRef.current) {
        window.cancelAnimationFrame(seekPreviewFrameRef.current);
        seekPreviewFrameRef.current = undefined;
      }
      activeEpisodeIdRef.current = undefined;
      pendingEpisodeIdRef.current = undefined;
      cancelFirstFrameRequest();
      removeMutedListener();
      ownedPlayer?.destroy?.();
      void clearDramaPreload();
      if (playerRef.current === ownedPlayer) playerRef.current = null;
      root.replaceChildren();
    };
  }, [
    cancelFirstFrameRequest,
    drama.id,
    drama.cover,
    markFirstFrameAfterPresentation,
    progressHooks,
    Boolean(initialEpisode),
    playerAttempt,
  ]);

  useEffect(() => {
    const suspend = () => {
      if (lifecycleSuspendedRef.current) return;
      lifecycleSuspendedRef.current = true;
      const player = playerRef.current;
      const media = player?.player?.media;
      resumeAfterLifecycleRef.current = Boolean(media && !media.paused);
      if (media) media.playbackRate = 1;
      if (player?.player) player.player.playbackRate = 1;
      pausePlayer(player);
      setLifecyclePauseCount((count) => count + 1);
    };

    const resume = () => {
      if (!lifecycleSuspendedRef.current) return;
      lifecycleSuspendedRef.current = false;
      if (!resumeAfterLifecycleRef.current) return;
      resumeAfterLifecycleRef.current = false;
      void playPlayer(playerRef.current).catch(() => undefined);
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') suspend();
      else resume();
    };

    window.addEventListener('pagehide', suspend);
    window.addEventListener('pageshow', resume);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.removeEventListener('pagehide', suspend);
      window.removeEventListener('pageshow', resume);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  const setPlaybackRate = (rate: number) => {
    const player = playerRef.current?.player;
    if (player?.media) player.media.playbackRate = rate;
    if (player) player.playbackRate = rate;
  };

  const getPlaybackRate = () =>
    playerRef.current?.player?.media?.playbackRate ??
    playerRef.current?.player?.playbackRate ??
    1;

  const seekTo = useCallback((seconds: number): boolean => {
    const media = playerRef.current?.player?.media;
    if (!media || !Number.isFinite(media.duration) || media.duration <= 0) return false;
    media.currentTime = Math.min(Math.max(0, seconds), media.duration);
    return true;
  }, []);

  // Refresh the authorized AUTO window after an unlock or episode switch without rebuilding the Player.
  useEffect(() => {
    if (!initialEpisode || firstFrameEpisodeId !== initialEpisode.id || !drama.episodes.length) return;
    void setupDramaAutoPreload(drama, drama.episodes);
  }, [drama.episodes, firstFrameEpisodeId, initialEpisode?.id]);

  return {
    rootRef,
    status,
    error,
    isSwitching,
    switchEpisode,
    endedCount,
    lifecyclePauseCount,
    isSeeking,
    currentTime,
    seekTo,
    seekTime: seekPreviewTime ?? currentTime,
    duration,
    isMuted,
    isFirstFrameReady: Boolean(initialEpisode && firstFrameEpisodeId === initialEpisode.id),
    pausePlayback: () => {
      const wasPlaying = Boolean(playerRef.current?.player?.media && !playerRef.current.player.media.paused);
      pausePlayer(playerRef.current);
      return wasPlaying;
    },
    resumePlayback: () => { void playPlayer(playerRef.current).catch(() => undefined); },
    retryPlayback: () => setPlayerAttempt(value => value + 1),
    setPlaybackRate,
    getPlaybackRate,
  };
}
