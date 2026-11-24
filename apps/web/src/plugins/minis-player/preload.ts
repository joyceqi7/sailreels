import { MINIS_DRAMA_PLAYER_POLICY, PRELOAD_SCENE } from './config';
import { buildAuthorizedPlaybackConfig } from './playback-config';
import { resolveMinisPlayer } from './sdk';
import type { DramaPlaybackSource, EpisodePlaybackSource } from './types';

type PreloadMode = 'manual' | 'auto' | 'clear';

interface PreloadSetupTask {
  mode: PreloadMode;
  key: string;
  promise: Promise<void>;
}

let preparePromise: Promise<void> | null = null;
let activePreloadTask: PreloadSetupTask | null = null;

/** Release theater tasks before the next route takes ownership of the shared SDK preloader. */
export function clearDramaPreload(): Promise<void> {
  const previous = activePreloadTask?.promise.catch(() => undefined) ?? Promise.resolve();
  const promise = previous.then(async () => {
    const Player = await resolveMinisPlayer();
    Player.preloader?.clearPreloadList?.();
    Player.preloader?.removeAllPreloadTask?.();
  }).catch(() => undefined);
  activePreloadTask = { mode: 'clear', key: '', promise };
  return promise;
}

function buildPreloadItem(
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
): Record<string, unknown> {
  return {
    ...buildAuthorizedPlaybackConfig(drama, episode),
    defaultDefinition: MINIS_DRAMA_PLAYER_POLICY.definition,
  };
}

function episodePreloadKey(
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
): string {
  return `${episode.albumId ?? drama.albumId ?? ''}:${episode.episodeId}`;
}

async function preparePlayerPreload(): Promise<void> {
  if (preparePromise) return preparePromise;
  preparePromise = (async () => {
    const Player = await resolveMinisPlayer();
    Player.setMediaInfoCacheConfig?.(MINIS_DRAMA_PLAYER_POLICY.mediaInfoCache);
    await Player.prepare?.({
      strategies: {
        preload: true,
      },
    });
  })().catch((error) => {
    preparePromise = null;
    throw error;
  });
  return preparePromise;
}

/**
 * Starts SDK/preload initialization while application data is still loading.
 * A later MANUAL/AUTO setup reuses the same promise.
 */
export function prepareMinisDramaPreload(): Promise<void> {
  return preparePlayerPreload().catch((error) => {
    console.warn('[preload] Failed to prepare the Minis preload module.', error);
  });
}

/** Whether this exact entry episode currently owns the MANUAL preload slot. */
export function hasManualEntryPreload(
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
): boolean {
  return (
    activePreloadTask?.mode === 'manual' &&
    activePreloadTask.key === episodePreloadKey(drama, episode)
  );
}

/** Preloads one episode from the discovery page using the manual scene. */
export function preloadDramaEpisode(
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
): Promise<void> {
  const key = episodePreloadKey(drama, episode);
  if (activePreloadTask?.mode === 'manual' && activePreloadTask.key === key) {
    return activePreloadTask.promise;
  }

  const previousTask =
    activePreloadTask?.promise.catch(() => undefined) ?? Promise.resolve();
  const promise = previousTask.then(async () => {
    await preparePlayerPreload();
    const Player = await resolveMinisPlayer();
    await Player.setPreloadScene?.(
      PRELOAD_SCENE.manual,
      MINIS_DRAMA_PLAYER_POLICY.manualPreload,
    );
    Player.preloader?.clearPreloadList?.();
    Player.preloader?.removeAllPreloadTask?.();
    await Player.setPreloadList?.([buildPreloadItem(drama, episode)]);
  }).catch((error) => {
    if (activePreloadTask?.mode === 'manual' && activePreloadTask.key === key) {
      activePreloadTask = null;
    }
    console.warn('[preload] Failed to preload the drama episode.', error);
  });

  activePreloadTask = { mode: 'manual', key, promise };
  return promise;
}

/**
 * Configures theater AUTO feed preload. For a discovery-warmed entry, call it
 * after the first frame so cleanup cannot steal that episode's download
 * window. For a direct theater entry, call it before creating the Player.
 */
export function setupDramaAutoPreload(
  drama: DramaPlaybackSource,
  episodes: EpisodePlaybackSource[],
): Promise<void> {
  if (!episodes.length) return Promise.resolve();
  const key = episodes
    .map((episode) => `${episode.albumId ?? drama.albumId ?? ''}:${episode.episodeId}`)
    .join('|');
  if (activePreloadTask?.mode === 'auto' && activePreloadTask.key === key) {
    return activePreloadTask.promise;
  }

  const previousTask =
    activePreloadTask?.promise.catch(() => undefined) ?? Promise.resolve();
  const promise = previousTask.then(async () => {
    await preparePlayerPreload();
    const Player = await resolveMinisPlayer();
    Player.preloader?.clearPreloadList?.();
    Player.preloader?.removeAllPreloadTask?.();
    await Player.setPreloadScene?.(
      PRELOAD_SCENE.autoFeed,
      MINIS_DRAMA_PLAYER_POLICY.autoPreload,
    );
    await Player.setPreloadList?.(
      episodes.map((episode) => buildPreloadItem(drama, episode)),
    );
  }).catch((error) => {
    if (activePreloadTask?.mode === 'auto' && activePreloadTask.key === key) {
      activePreloadTask = null;
    }
    console.warn('[preload] Failed to configure theater auto preload.', error);
  });

  activePreloadTask = { mode: 'auto', key, promise };
  return promise;
}
