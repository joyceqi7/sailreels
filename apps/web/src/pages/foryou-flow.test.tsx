// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ForYouPage } from './ForYouPage';
import { ProfilePage } from './AccountPages';
import { MOCK_CATALOG } from '../api/catalog-mock';
import * as catalog from '../api/catalog';
import * as account from '../api/account';
import * as subscriptions from '../api/subscriptions';

const player = vi.hoisted(() => ({ hook: vi.fn(), switch: vi.fn(), ended: 0, seek: vi.fn(), resume: vi.fn() }));
vi.mock('../hooks/useMinisPlayer', () => ({ useMinisPlayer: (drama: unknown, episode: unknown) => {
  player.hook(drama, episode);
  return { rootRef: { current: null }, switchEpisode: player.switch, pausePlayback: vi.fn(),
    resumePlayback: player.resume, retryPlayback: vi.fn(), endedCount: player.ended, lifecyclePauseCount: 0,
    isSeeking: false, seekTime: 0, currentTime: 0, duration: 60, isMuted: false, isFirstFrameReady: true,
    isSwitching: false, seekTo: player.seek, setPlaybackRate: vi.fn(), getPlaybackRate: () => 1 };
} }));

const ids = MOCK_CATALOG.map(d => String(d.id));
const page = (path = '/playlet/foryou') => render(<MemoryRouter initialEntries={[path]}><Routes>
  <Route path="/playlet/foryou" element={<ForYouPage />} />
  <Route path="/playlet/profile" element={<ProfilePage />} />
</Routes></MemoryRouter>);
const lastEpisode = () => player.hook.mock.calls.at(-1)?.[1] as { id: string } | undefined;

beforeEach(() => {
  player.ended = 0; player.hook.mockClear(); player.switch.mockReset().mockResolvedValue(true);
  player.seek.mockReset().mockReturnValue(true); player.resume.mockReset();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('plays episode 1 of the first drama through one feed-scoped Player and offers Continue to episode 2', async () => {
  page();
  await waitFor(() => expect(lastEpisode()?.id).toBe(`${ids[0]}:1`));
  // A constant drama identity keeps useMinisPlayer from rebuilding the Player between dramas.
  expect(player.hook.mock.calls.every(([drama]) => drama.id === 'for-you')).toBe(true);
  const cta = await screen.findByRole('link', { name: /Continue to Episode 2/ });
  expect(cta.getAttribute('href')).toBe(`/playlet/theater?id=${ids[0]}&seq=2`);
  expect(screen.getByRole('link', { name: 'For You' }).className).toContain('is-active');
  expect(screen.queryByRole('link', { name: 'VIP' })).toBeNull();
});

it('an ended episode moves on to the next drama with playNext, not a new Player', async () => {
  const view = page();
  await waitFor(() => expect(lastEpisode()?.id).toBe(`${ids[0]}:1`));
  // Next drama's first episode is warmed into the AUTO preload window before the switch.
  await waitFor(() => expect(player.hook.mock.calls.at(-1)?.[0].episodes.map((e: { id: string }) => e.id))
    .toEqual([`${ids[0]}:1`, `${ids[1]}:1`]));
  player.ended = 1;
  view.rerender(<MemoryRouter initialEntries={['/playlet/foryou']}><Routes>
    <Route path="/playlet/foryou" element={<ForYouPage />} /></Routes></MemoryRouter>);
  await waitFor(() => expect(player.switch).toHaveBeenCalledWith(expect.objectContaining({ id: `${ids[1]}:1` })));
  await waitFor(() => expect(lastEpisode()?.id).toBe(`${ids[1]}:1`));
});

it('skips dramas whose first episode is not playable instead of showing someone else\'s video', async () => {
  const real = catalog.getEpisodeAccess;
  vi.spyOn(catalog, 'getEpisodeAccess').mockImplementation(async (id, seq) =>
    String(id) === ids[0] ? { access: 'locked', unlock_price_beans: 100, episode: null } : real(id, seq));
  page();
  await waitFor(() => expect(lastEpisode()?.id).toBe(`${ids[1]}:1`));
  expect(player.hook.mock.calls.some(([, episode]) => episode?.id === `${ids[0]}:1`)).toBe(false);
});

it('Continue resumes a saved place, and feed plays never overwrite existing progress', async () => {
  vi.spyOn(account, 'getProgress').mockResolvedValue(
    { drama_id: Number(ids[0]), last_seq: 3, position_seconds: 12, updated_at: new Date().toISOString() });
  const save = vi.spyOn(account, 'saveProgress');
  page();
  const cta = await screen.findByRole('link', { name: /Continue to Episode 3/ });
  expect(cta.getAttribute('href')).toBe(`/playlet/theater?id=${ids[0]}&seq=3`);
  act(() => { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('pagehide')); });
  expect(save).not.toHaveBeenCalled();
});

it('Profile leads with a VIP card that opens the subscription page', async () => {
  vi.spyOn(subscriptions, 'getSubscription').mockResolvedValue({ active: true, state: 'active', is_sandbox: false,
    renewal_normal: true, benefit_end_time: '2026-12-01T00:00:00Z' } as subscriptions.SubscriptionStatus);
  page('/playlet/profile');
  const card = await screen.findByRole('link', { name: /SailReels VIP/ });
  expect(card.getAttribute('href')).toBe('/playlet/subscription');
  await waitFor(() => expect(card.textContent).toMatch(/Active until .*2026.*Manage/));
});
