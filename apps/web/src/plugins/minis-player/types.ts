export type MinisPlayerChannel = 'byteplus' | 'volcengine';

export interface DramaPlaybackSource {
  /** Fallback for APIs that keep album_id on the drama instead of each episode. */
  albumId?: string;
  cover?: string;
}

export interface EpisodePlaybackSource {
  id?: string;
  albumId?: string;
  vid: string;
  episodeId: string;
  playAuthToken?: string;
  poster?: string;
}

/** Documented episode identity accepted by new Player, playNext and preload. */
export interface MinisVideoIdentityConfig {
  vid: string;
  albumId?: string;
  episodeId: string;
  getVideoByToken?: {
    playAuthToken: string;
    needPoster: boolean;
  };
}

export interface MinisProgressDragData {
  /** Target time represented by the progress thumb. */
  currentTime?: number;
  /** Media time after applying a segmented-timeline offset, when configured. */
  seekTime?: number;
  percent?: number;
}

export interface PlayerConfigHooks {
  onProgressMoveStart?: (data?: MinisProgressDragData) => void;
  onProgressMove?: (data?: MinisProgressDragData) => void;
  onProgressMoveEnd?: (data?: MinisProgressDragData) => void;
}

export interface MinisProgressPlugin {
  focus?: () => void;
  blur?: () => void;
  useHooks?: (
    hook: 'dragstart' | 'drag' | 'dragend',
    handler: (...args: unknown[]) => boolean,
  ) => void;
}

export interface MinisPlayerMedia {
  muted?: boolean;
  playbackRate?: number;
  media?: HTMLVideoElement;
  plugins?: {
    progress?: MinisProgressPlugin;
  };
  getPlugin?: (name: 'progress') => MinisProgressPlugin | undefined;
  play?: () => Promise<void> | void;
  pause?: () => void;
}

export interface MinisPlayerInstance {
  player?: MinisPlayerMedia;
  preLoadData?: {
    hit?: 0 | 1;
    duration?: number;
    length?: number;
  };
  on?: (event: string, handler: (...args: unknown[]) => void) => void;
  once?: (event: string, handler: (...args: unknown[]) => void) => void;
  play?: () => Promise<void> | void;
  pause?: () => void;
  playNext?: (config: Record<string, unknown>, isNewVideo?: boolean) => Promise<void>;
  destroy?: () => void;
}

export interface MinisPlayerConstructor {
  new (config: Record<string, unknown>): MinisPlayerInstance;
  Events?: Record<string, unknown>;
  setDebug?: (enabled: boolean) => void;
  setMediaInfoCacheConfig?: (config: {
    enable: boolean;
    cacheType: 'memory' | 'localStorage';
    expireTime: number;
    maxEntries?: number;
  }) => void;
  prepare?: (config: Record<string, unknown>) => Promise<void> | void;
  setPreloadScene?: (scene: number, config?: Record<string, unknown>) => Promise<void> | void;
  setPreloadList?: (list: Array<Record<string, unknown>>) => Promise<void> | void;
  preloader?: {
    removeAllPreloadTask?: () => void;
    clearPreloadList?: () => void;
  };
}

export interface TTMinisPlayerApi {
  /** Public runtime flag set by the TikTok Minis SDK. */
  readonly isMinisRuntime?: boolean;
  getPlayer?: (
    channel?: MinisPlayerChannel,
  ) => Promise<MinisPlayerConstructor> | MinisPlayerConstructor;
}
