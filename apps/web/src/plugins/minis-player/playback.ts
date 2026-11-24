import { buildMinisPlayerConfig } from './playback-config';
import { resolveMinisPlayer } from './sdk';
import type {
  DramaPlaybackSource,
  EpisodePlaybackSource,
  MinisPlayerConstructor,
  MinisPlayerInstance,
  PlayerConfigHooks,
} from './types';

export interface CreatedMinisPlayer {
  Player: MinisPlayerConstructor;
  player: MinisPlayerInstance;
}

/** Creates the single Player instance owned by a theater. */
export async function createMinisDramaPlayer(
  root: HTMLElement,
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
  hooks: PlayerConfigHooks = {},
): Promise<CreatedMinisPlayer> {
  const Player = await resolveMinisPlayer();
  const config = buildMinisPlayerConfig(root, drama, episode, hooks);
  return { Player, player: new Player(config) };
}

/** Reuses the existing instance when switching episodes. */
export async function playNextEpisode(
  player: MinisPlayerInstance,
  root: HTMLElement,
  drama: DramaPlaybackSource,
  episode: EpisodePlaybackSource,
  hooks: PlayerConfigHooks = {},
): Promise<void> {
  if (!player.playNext) throw new Error('The Minis Player does not expose playNext().');

  // playNext may rebuild the autoplay/unmute plugins even though it reuses the
  // Player instance. Carry the user's current sound choice into the new source
  // so an already-unmuted session does not briefly degrade to mute again.
  const previousMuted =
    player.player?.media?.muted ??
    player.player?.muted;
  const config = {
    ...buildMinisPlayerConfig(root, drama, episode, hooks),
    ...(typeof previousMuted === 'boolean' ? { muted: previousMuted } : {}),
  };
  if (player.pause) player.pause();
  else player.player?.pause?.();
  await player.playNext(config, true);

  if (typeof previousMuted === 'boolean' && player.player) {
    player.player.muted = previousMuted;
    if (player.player.media) {
      player.player.media.muted = previousMuted;
      player.player.media.defaultMuted = previousMuted;
    }
  }

  try {
    const playResult = player.play ? player.play() : player.player?.play?.();
    await playResult;
  } catch {
    // The episode switch succeeded; a user gesture can resume if autoplay is blocked.
  }
}
