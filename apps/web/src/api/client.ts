import { MOCK_DRAMAS } from './mock-data';
import type { DemoDramaDetailResponse as DramaDetailResponse, DemoDramaListResponse as DramaListResponse } from './types';

/** Set to false when a real backend is available. */
export const MOCK_API_ENABLED = true;
const API_BASE_URL = '/api/v1';

function mockResponse<T>(payload: T): Promise<T> {
  return Promise.resolve(structuredClone(payload));
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) throw new Error(`API request failed with ${response.status}.`);
  return response.json() as Promise<T>;
}

export function getDramaList(): Promise<DramaListResponse> {
  if (MOCK_API_ENABLED) {
    const dramas = MOCK_DRAMAS.map(({ episodes, ...summary }) => ({
      ...summary,
      preload_episode: episodes[0],
    }));
    return mockResponse({ data: { dramas } });
  }
  return request<DramaListResponse>('/dramas');
}

export function getDramaDetail(dramaId: string): Promise<DramaDetailResponse> {
  if (MOCK_API_ENABLED) {
    const drama = MOCK_DRAMAS.find((item) => item.drama_id === dramaId);
    if (!drama) return Promise.reject(new Error(`Drama "${dramaId}" was not found.`));
    return mockResponse({ data: { drama } });
  }
  return request<DramaDetailResponse>(`/dramas/${encodeURIComponent(dramaId)}`);
}
