import { MOCK_CATALOG, MOCK_EPISODES, hasPreviewRight } from './catalog-mock';
import { hasPreviewSubscription } from './subscription-preview';
import type { DramaDetailResponse, DramaListResponse, EpisodeAccessResponse } from './types';
import { API_BASE, MOCK_API_ENABLED } from './config';
import { apiFetch } from '../minis/session';
import type { components } from '../../../../packages/api-types/schema';

/** Mock and live use the same generated backend response shapes. */
export { MOCK_API_ENABLED } from './config';

function mockResponse<T>(payload: T): Promise<T> {
  return Promise.resolve(structuredClone(payload));
}

async function request<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`API request failed with ${response.status}.`);
    return await response.json() as T;
  } finally { clearTimeout(timer); }
}

export function getDramaList(): Promise<DramaListResponse> {
  if (MOCK_API_ENABLED) {
    return mockResponse(MOCK_CATALOG);
  }
  return request<DramaListResponse>('/dramas');
}

function validateDramaId(dramaId: string | number) {
  if (!/^[1-9]\d*$/.test(String(dramaId)) || !Number.isSafeInteger(Number(dramaId))) {
    throw new Error('Invalid drama ID.');
  }
}

export async function getDramaDetail(dramaId: string): Promise<DramaDetailResponse> {
  validateDramaId(dramaId);
  if (MOCK_API_ENABLED) {
    const drama = MOCK_CATALOG.find((item) => String(item.id) === dramaId);
    if (!drama) return Promise.reject(new Error(`Drama "${dramaId}" was not found.`));
    return mockResponse(drama);
  }
  return request<DramaDetailResponse>(`/dramas/${dramaId}`);
}

export async function getEpisodeAccess(dramaId: string | number, seq: number): Promise<EpisodeAccessResponse> {
  validateDramaId(dramaId);
  if (!Number.isSafeInteger(seq) || seq < 1) throw new Error('Invalid episode number.');
  if (!MOCK_API_ENABLED) return apiFetch<EpisodeAccessResponse>(`/dramas/${dramaId}/episodes/${seq}/access`);
  const episode = MOCK_EPISODES[String(dramaId)]?.find((item) => item.episode_number === seq);
  if (!episode) throw new Error('Episode was not found.');
  // Mirror the backend seed: only the first episode is free. No client unlock.
  if (seq > 1 && !hasPreviewRight(String(dramaId), seq) && !hasPreviewSubscription()) {
    return mockResponse({ access: 'locked', unlock_price_beans: 100, episode: null });
  }
  return mockResponse({ access: seq > 1 ? hasPreviewSubscription() ? 'subscribed' : 'unlocked' : 'free', unlock_price_beans: null, episode: {
    seq, title: episode.title, locked: false, album_id: episode.album_id,
    episode_id: episode.episode_id, vid: episode.vid, poster_url: episode.poster_url ?? null,
  } });
}

export async function getEpisodeList(dramaId: string): Promise<components['schemas']['EpisodeListOut']> {
  validateDramaId(dramaId);
  if (!MOCK_API_ENABLED) return apiFetch(`/dramas/${dramaId}/episodes`);
  const drama = await getDramaDetail(dramaId);
  const episodes = await Promise.all(Array.from({ length: drama.total_episodes }, async (_, index) => {
    const seq = index + 1;
    const access = await getEpisodeAccess(dramaId, seq);
    return access.episode ?? { seq, title: `Episode ${seq}`, locked: true };
  }));
  return { drama_id: drama.id, free_episodes: drama.free_episodes, unlock_price_beans: drama.unlock_price_beans,
    subscribed: hasPreviewSubscription(), next_locked_seq: episodes.find(e => e.locked)?.seq ?? null, episodes };
}
