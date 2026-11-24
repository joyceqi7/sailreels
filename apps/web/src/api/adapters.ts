import type { Drama, DramaSummary, EpisodeSource } from '../types/drama';
import type { DramaDTO, DramaSummaryDTO, EpisodeDTO } from './types';

export function mapEpisode(dto: EpisodeDTO): EpisodeSource {
  return {
    id: dto.episode_id,
    albumId: dto.album_id,
    episodeId: dto.episode_id,
    episodeNumber: dto.episode_number,
    title: dto.title,
    description: dto.description,
    vid: dto.vid,
    playAuthToken: dto.play_auth_token,
    poster: dto.poster_url,
  };
}

export function mapDrama(dto: DramaDTO): Drama {
  return {
    ...mapDramaSummary(dto),
    episodes: dto.episodes.map(mapEpisode),
  };
}

export function mapDramaSummary(dto: DramaSummaryDTO): DramaSummary {
  return {
    id: dto.drama_id,
    title: dto.title,
    subtitle: dto.subtitle,
    category: dto.category,
    // The discovery card represents the episode that will open first, so its
    // artwork must come from that episode rather than an unrelated drama cover.
    cover: dto.preload_episode?.poster_url ?? dto.cover_url,
    episodeCount: dto.episode_count,
    preloadEpisode: dto.preload_episode
      ? mapEpisode(dto.preload_episode)
      : undefined,
  };
}
