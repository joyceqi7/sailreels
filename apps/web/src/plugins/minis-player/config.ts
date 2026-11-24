/**
 * Customer-editable defaults shared by playback and preload.
 *
 * Keep `definition` identical in both paths. VePlayer keys its media-info and
 * video-data caches by episode and definition, so a mismatch prevents a hit.
 */
export const MINIS_DRAMA_PLAYER_POLICY = {
  definition: '720p',
  manualPreload: {
    preloadTime: 5,
  },
  autoPreload: {
    prevCount: 1,
    nextCount: 2,
    preloadTime: 5,
  },
  mediaInfoCache: {
    enable: true,
    cacheType: 'memory',
    expireTime: 30 * 60 * 1_000,
    maxEntries: 100,
  },
} as const;

export const PRELOAD_SCENE = {
  manual: 0,
  autoFeed: 1,
} as const;
