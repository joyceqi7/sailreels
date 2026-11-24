import type { components, paths } from '../../../../packages/api-types/schema';

/** Backend v1 contract, generated from docs/openapi/v1.json. */
export type CatalogDramaDTO = components['schemas']['DramaOut'];
export type DramaListResponse = paths['/api/v1/dramas']['get']['responses'][200]['content']['application/json'];
export type DramaDetailResponse = components['schemas']['DramaOut'];
export type EpisodeAccessResponse = components['schemas']['AccessOut'];

/** Demo-only playback payload. This is NOT the backend /dramas/{id} response. */
export interface EpisodeDTO {
  episode_id: string;
  album_id: string;
  episode_number: number;
  title: string;
  description: string;
  vid: string;
  play_auth_token?: string;
  poster_url?: string;
}

export interface DramaDTO {
  drama_id: string;
  title: string;
  subtitle: string;
  category: 'Popular' | 'Original+' | 'Female' | 'Male' | 'New';
  cover_url: string;
  episode_count: number;
  episodes: EpisodeDTO[];
}

/** Existing demo-page compatibility; never treat these as backend v1 responses. */
export interface DramaSummaryDTO extends Omit<DramaDTO, 'episodes'> {
  preload_episode?: EpisodeDTO;
}
export interface DemoDramaListResponse {
  data: { dramas: DramaSummaryDTO[] };
}
export interface DemoDramaDetailResponse {
  data: { drama: DramaDTO };
}
