import type {
  DramaPlaybackSource,
  EpisodePlaybackSource,
  MinisVideoIdentityConfig,
  PlayerConfigHooks,
} from './types';
import { MINIS_DRAMA_PLAYER_POLICY } from './config';
import { isMinisContainerEnvironment } from './sdk';

/** API identity shared by initial playback, playNext and preload. */
export function buildAuthorizedPlaybackConfig(
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
): MinisVideoIdentityConfig {
  const config: MinisVideoIdentityConfig = {
    vid: episode.vid,
    albumId: episode.albumId ?? drama.albumId,
    episodeId: episode.episodeId,
  };

  // Newer Minis runtimes resolve reviewed episodes from the three identifiers.
  // Older runtimes receive the optional temporary token through this branch.
  if (episode.playAuthToken) {
    config.getVideoByToken = {
      playAuthToken: episode.playAuthToken,
      needPoster: true,
    };
  }
  return config;
}

/** UI-neutral Minis Player configuration used by the theater page. */
export function buildMinisPlayerConfig(
  root: HTMLElement,
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
  hooks: PlayerConfigHooks = {},
): Record<string, unknown> {
  const minisSoundConfig = isMinisContainerEnvironment()
    ? { muted: false }
    : {};

  return {
    root,
    ...buildAuthorizedPlaybackConfig(drama, episode),
    autoplay: true,
    ...minisSoundConfig,
    enableDegradeMuteAutoplay: true,
    enableMp4MSE: true,
    retryCount: 3,
    defaultDefinition: MINIS_DRAMA_PLAYER_POLICY.definition,
    closeVideoClick: false,
    closeVideoDblclick: true,
    // videoFillMode: 'contain',
     videoFillMode: 'fillWidth',
    lang: 'en',
    controls: { mode: 'bottom' },
    mobile: {
      gradient: 'none',
      darkness: false,
      closedbClick: true,
      focusVideoClick: true,
      isTouchingSeek: false,
      gestureY: false,
    },
    ignores: [
      'moreButtonPlugin',
      'enter',
      'fullscreen',
      'volume',
      'play',
      'time',
      'pip',
      'replay',
      'playbackrate',
      'sdkDefinitionPlugin',
    ],
    commonStyle: { playedColor: '#ffffff' },
    adaptRange: {
      enable: true,
      minCacheDuration: 15,
      maxCacheDuration: 40,
    },
    progress: {
      onMoveStart: hooks.onProgressMoveStart,
      onMove: hooks.onProgressMove,
      onMoveEnd: hooks.onProgressMoveEnd,
    },
    sdkErrorPlugin: { isNeedRefreshButton: false },
    start: { disableAnimate: true, isShowPause: true },
    ...(episode.poster
      ? {
          poster: {
            poster: episode.poster,
            hideCanplay: true,
            // fillMode: 'contain',
            fillMode: 'fillWidth',
          },
        }
      : {}),
  };
}
