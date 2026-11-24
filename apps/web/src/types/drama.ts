export interface EpisodeSource {
  id: string;
  albumId: string;
  episodeNumber: number;
  title: string;
  description: string;
  vid: string;
  episodeId: string;
  playAuthToken?: string;
  poster?: string;
}

export interface DramaSummary {
  id: string;
  title: string;
  subtitle: string;
  category: 'Popular' | 'Original+' | 'Female' | 'Male' | 'New';
  cover: string;
  episodeCount: number;
  /** Optional list-API hint used to start first-frame preload immediately. */
  preloadEpisode?: EpisodeSource;
}

export interface Drama extends DramaSummary {
  episodes: EpisodeSource[];
}
