import { MOCK_DRAMAS } from './mock-data';
import type { DramaListResponse, EpisodeDTO } from './types';

// Local numeric business IDs; the original demo routes retain their own IDs.
const fixtures = MOCK_DRAMAS.map((drama, index) => ({ id: index === 0 ? 2 : 1, drama }));

/** Metadata only: catalog responses never authorize or expose playable media. */
export const MOCK_CATALOG: DramaListResponse = fixtures.map(({ id, drama }) => ({
  id, title: drama.title, description: drama.subtitle, cover_url: drama.cover_url,
  total_episodes: 3, free_episodes: 1, unlock_price_beans: 100,
}));

/** Internal fixtures for the mock access endpoint, not for page playback. */
export const MOCK_EPISODES: Record<string, EpisodeDTO[]> = Object.fromEntries(
  fixtures.map(({ id, drama }) => [String(id), drama.episodes.slice(0, 3)]),
);

/** Preview-only state. It is never used by the live access or payment APIs. */
const previewRights = new Set<string>();
export const hasPreviewRight = (dramaId: string, seq: number) => previewRights.has(`${dramaId}:${seq}`);
export const grantPreviewRight = (dramaId: string, seq: number) => previewRights.add(`${dramaId}:${seq}`);
export const resetPreviewRights = () => previewRights.clear();
