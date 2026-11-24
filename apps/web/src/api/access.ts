import { getEpisodeAccess } from './catalog';
import type { EpisodeAccessResponse } from './types';
import type { EpisodeSource } from '../types/drama';

export class EpisodeLockedError extends Error {
  constructor() { super('This episode is locked.'); }
}

/** Fail closed: neither metadata nor a partial/unknown response grants playback. */
export function resolveEpisodeAccess(response: EpisodeAccessResponse, dramaId: string, seq: number): EpisodeSource {
  if (response?.access === 'locked') throw new EpisodeLockedError();
  const episode = response?.episode;
  const nonempty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
  if (!['free', 'unlocked', 'subscribed'].includes(response?.access) || !episode ||
      episode.seq !== seq || episode.locked === true || !nonempty(episode.album_id) || !nonempty(episode.episode_id) || !nonempty(episode.vid)) {
    throw new Error('Valid playback permission and media information are required.');
  }
  return {
    id: `${dramaId}:${seq}`, episodeNumber: seq,
    title: nonempty(episode.title) ? episode.title : `Episode ${seq}`, description: '',
    albumId: episode.album_id, episodeId: episode.episode_id, vid: episode.vid,
    poster: nonempty(episode.poster_url) ? episode.poster_url : undefined,
  };
}

export async function loadPlayableEpisode(dramaId: string, seq: number) {
  return resolveEpisodeAccess(await getEpisodeAccess(dramaId, seq), dramaId, seq);
}
