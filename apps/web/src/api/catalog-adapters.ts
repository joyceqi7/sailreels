import type { DramaSummary, EpisodeSource } from '../types/drama';
import type { CatalogDramaDTO } from './types';

export interface CatalogDramaDetail extends Omit<DramaSummary, 'preloadEpisode'> {
  freeEpisodes: number;
  unlockPriceBeans: number;
  episodes: (Pick<EpisodeSource, 'id' | 'episodeNumber' | 'title' | 'description'> & { poster?: string })[];
}

export function mapDrama(dto: CatalogDramaDTO): CatalogDramaDetail {
  return {
    ...mapDramaSummary(dto),
    freeEpisodes: dto.free_episodes,
    unlockPriceBeans: dto.unlock_price_beans,
    episodes: Array.from({ length: dto.total_episodes }, (_, index) => ({
      id: `${dto.id}:${index + 1}`,
      episodeNumber: index + 1,
      title: `Episode ${index + 1}`,
      description: '',
    })),
  };
}

export function mapDramaSummary(dto: CatalogDramaDTO): Omit<DramaSummary, 'preloadEpisode'> {
  return {
    id: String(dto.id),
    title: dto.title,
    subtitle: dto.description,
    // TODO(confirm): v1 has no category field; use the existing default tab.
    category: 'Popular',
    cover: dto.cover_url,
    episodeCount: dto.total_episodes,
  };
}
