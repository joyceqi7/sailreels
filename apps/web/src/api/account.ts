import type { components } from '../../../../packages/api-types/schema';
import { apiFetch, getSessionOwner, getSessionProfile, type ProfileResponse } from '../minis/session';
import { authorizeProfile } from '../minis/sdk';
import { MOCK_API_ENABLED } from './config';
import { MOCK_CATALOG } from './catalog-mock';

export type Progress = components['schemas']['ProgressOut'];
export type History = components['schemas']['HistoryOut'];
export type Wallet = components['schemas']['WalletOut'];
const history = new Map<string, Progress>();
// Serialize writes from one player: a slow previous episode save must finish before its successor.
let saveQueue: Promise<unknown> = Promise.resolve();

export async function getProgress(dramaId: string): Promise<Progress | null> {
  if (!MOCK_API_ENABLED) return apiFetch(`/me/progress/${encodeURIComponent(dramaId)}`);
  return history.get(dramaId) ?? null;
}
export function saveProgress(dramaId: string, seq: number, seconds: number): Promise<Progress> {
  const owner = getSessionOwner();
  const position = Math.max(0, Math.min(86400, Math.floor(seconds)));
  const operation = async (): Promise<Progress> => {
    if (!MOCK_API_ENABLED && owner !== getSessionOwner()) throw new Error('Session changed');
    if (!MOCK_API_ENABLED) return apiFetch(`/me/progress/${encodeURIComponent(dramaId)}`, {
      method: 'PUT', body: JSON.stringify({ seq, position_seconds: position }),
    });
    const progress = { drama_id: Number(dramaId), last_seq: seq, position_seconds: position, updated_at: new Date().toISOString() };
    history.set(dramaId, progress); return progress;
  };
  const task = saveQueue.catch(() => undefined).then(operation); saveQueue = task;
  return task;
}
export async function getHistory(offset = 0): Promise<History> {
  if (!MOCK_API_ENABLED) return apiFetch(`/me/history?offset=${offset}`);
  const rows = [...history.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return { has_more: rows.length > offset + 20, items: rows.slice(offset, offset + 20).map(p => {
    const drama = MOCK_CATALOG.find(d => d.id === p.drama_id);
    return { ...p, title: drama?.title ?? 'Drama', cover_url: drama?.cover_url ?? '', available: Boolean(drama) };
  }) };
}
export async function getWallet(offset = 0): Promise<Wallet> {
  if (!MOCK_API_ENABLED) return apiFetch(`/me/wallet?offset=${offset}`);
  return { beans_balance: null, items: [], has_more: false };
}
export const getProfile = (): Promise<ProfileResponse> => MOCK_API_ENABLED
  ? Promise.resolve({ open_id: 'preview', nickname: 'Drama fan', avatar_url: null }) : getSessionProfile();
export async function connectProfile(): Promise<ProfileResponse> {
  if (MOCK_API_ENABLED) return getProfile();
  await authorizeProfile();
  return apiFetch('/auth/authorize', { method: 'POST' });
}
