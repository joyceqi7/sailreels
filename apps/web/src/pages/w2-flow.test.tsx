// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SquarePage } from './SquarePage';
import { DetailPage } from './DetailPage';
import { TheaterPage } from './TheaterPage';
import { grantPreviewRight, resetPreviewRights } from '../api/catalog-mock';
import { getEpisodeAccess } from '../api/catalog';
import * as catalog from '../api/catalog';
import * as payments from '../api/monetization';

const player = vi.hoisted(() => ({ hook: vi.fn(), switch: vi.fn(), pause: vi.fn(), resume: vi.fn(), ended: 0 }));
vi.mock('../plugins/minis-player', () => ({ preloadDramaEpisode: vi.fn(), prepareMinisDramaPreload: vi.fn() }));
vi.mock('../hooks/useMinisPlayer', () => ({ useMinisPlayer: (drama: unknown, episode: unknown) => {
  player.hook(drama, episode);
  return { rootRef: { current: null }, switchEpisode: player.switch, pausePlayback: player.pause,
    resumePlayback: player.resume, retryPlayback: vi.fn(), endedCount: player.ended,
    lifecyclePauseCount: 0, isSeeking: false, seekTime: 0, duration: 60, isMuted: false,
    isFirstFrameReady: true, isSwitching: false, setPlaybackRate: vi.fn(), getPlaybackRate: () => 1 };
} }));

function view(path = '/playlet/square') {
  return <MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/playlet/square" element={<SquarePage />} />
    <Route path="/playlet/detail" element={<DetailPage />} />
    <Route path="/playlet/theater" element={<TheaterPage />} />
  </Routes></MemoryRouter>;
}
const page = (path?: string) => render(view(path));
beforeEach(() => {
  resetPreviewRights(); player.ended = 0; player.hook.mockClear();
  player.switch.mockReset().mockResolvedValue(true); player.pause.mockReturnValue(true);
  payments.rememberPendingOrder('1', 2); payments.rememberPendingOrder('1', 3);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('uses v1 numeric catalog IDs through discovery, details and authorized first playback', async () => {
  const user = userEvent.setup(); page();
  const cards = await screen.findAllByRole('button', { name: /Sometimes the truth|One day|Love|Drama|Forbidden|Test/i });
  await user.click(cards[0]);
  expect(await screen.findByRole('heading', { level: 1 })).toBeTruthy();
  expect(screen.getByText(/1 free · 100 Beans/)).toBeTruthy();
  await user.click(screen.getByRole('link', { name: 'Start watching' }));
  await waitFor(() => expect(player.hook.mock.calls.some(([, episode]) => episode?.episodeNumber === 1)).toBe(true));
  expect(player.hook.mock.calls.every(([drama]) => drama.episodes.length <= 1)).toBe(true);
});

it('AUTO preload contains only the contiguous authorized window and rechecks on entering the episode', async () => {
  grantPreviewRight('1', 2);
  const access = vi.spyOn(catalog, 'getEpisodeAccess');
  const user = userEvent.setup(); page('/playlet/theater?id=1');
  await waitFor(() => expect(player.hook.mock.calls.some(([d]) => d.episodes.some((e: { episodeNumber: number }) => e.episodeNumber === 2))).toBe(true));
  expect(player.hook.mock.calls.every(([d]) => d.episodes.every((e: { episodeNumber: number }) => e.episodeNumber <= 2))).toBe(true);
  const before = access.mock.calls.filter(([, seq]) => seq === 2).length;
  await user.click(screen.getByRole('button', { name: /Drama · 3 Episodes/ }));
  await user.click(screen.getByRole('button', { name: 'Episode 2' }));
  await waitFor(() => expect(player.switch).toHaveBeenCalled());
  expect(access.mock.calls.filter(([, seq]) => seq === 2).length).toBeGreaterThan(before);
  expect(player.switch.mock.calls[0][0].episodeNumber).toBe(2);
});

it('checks a selected locked episode before playNext and opens an explicit unlock choice', async () => {
  const user = userEvent.setup(); page('/playlet/theater?id=1');
  await waitFor(() => expect(player.hook.mock.calls.some(([, e]) => e?.episodeNumber === 1)).toBe(true));
  await user.click(screen.getByRole('button', { name: /Drama · 3 Episodes/ }));
  await user.click(screen.getByRole('button', { name: 'Episode 2, locked' }));
  expect(await screen.findByRole('dialog', { name: 'Unlock episode 2' })).toBeTruthy();
  expect(player.switch).not.toHaveBeenCalled();
  expect(player.hook.mock.calls.every(([, episode]) => !episode || episode.episodeNumber === 1)).toBe(true);
});

it('completes a preview Beans purchase, confirms access and only then switches the player', async () => {
  const user = userEvent.setup(); page('/playlet/theater?id=1');
  await user.click(await screen.findByRole('button', { name: /Drama · 3 Episodes/ }));
  await user.click(screen.getByRole('button', { name: 'Episode 2, locked' }));
  await user.click(await screen.findByRole('button', { name: /Single episode.*100 Beans/ }));
  expect(await screen.findByRole('dialog', { name: 'Preview payment' })).toBeTruthy();
  expect((await getEpisodeAccess('1', 2)).access).toBe('locked');
  await user.click(screen.getByRole('button', { name: 'Complete preview payment' }));
  await waitFor(() => expect(player.switch).toHaveBeenCalledTimes(1));
  expect(player.switch.mock.calls[0][0].episodeNumber).toBe(2);
  expect((await getEpisodeAccess('1', 2)).access).toBe('unlocked');
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('does not unlock after cancelling a payment or closing an ad early', async () => {
  const user = userEvent.setup(); page('/playlet/theater?id=1');
  await user.click(await screen.findByRole('button', { name: /Drama · 3 Episodes/ }));
  await user.click(screen.getByRole('button', { name: 'Episode 2, locked' }));
  await user.click(await screen.findByRole('button', { name: /Single episode.*100 Beans/ }));
  await user.click(await screen.findByRole('button', { name: 'Cancel payment' }));
  expect(await screen.findByText(/Payment cancelled/)).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Watch an ad · unlock this episode' }));
  await user.click(await screen.findByRole('button', { name: 'Close ad early' }));
  expect(await screen.findByText('Watch the full ad to unlock this episode.')).toBeTruthy();
  expect(player.switch).not.toHaveBeenCalled();
  expect((await getEpisodeAccess('1', 2)).access).toBe('locked');
});

it('claims an ad only after explicit completion and refetches playback permission', async () => {
  const user = userEvent.setup(); const claim = vi.spyOn(payments, 'claimReward'); page('/playlet/theater?id=1');
  await user.click(await screen.findByRole('button', { name: /Drama · 3 Episodes/ }));
  await user.click(screen.getByRole('button', { name: 'Episode 2, locked' }));
  await user.click(await screen.findByRole('button', { name: 'Watch an ad · unlock this episode' }));
  expect(claim).not.toHaveBeenCalled();
  await user.click(await screen.findByRole('button', { name: 'Finish watching' }));
  await waitFor(() => expect(player.switch).toHaveBeenCalledTimes(1));
  expect(claim).toHaveBeenCalledTimes(1);
  expect(player.switch.mock.calls[0][0].vid).toBeTruthy();
});

it('keeps delayed orders across closing/reopening the panel and never creates another one', async () => {
  const user = userEvent.setup(); const create = vi.spyOn(payments, 'createBeansOrder'); page('/playlet/theater?id=1');
  const select = async () => {
    await user.click(screen.getByRole('button', { name: /Drama · 3 Episodes/ }));
    await user.click(screen.getByRole('button', { name: 'Episode 2, locked' }));
  };
  await waitFor(() => expect(player.hook.mock.calls.some(([, e]) => e?.episodeNumber === 1)).toBe(true));
  await select();
  await user.click(await screen.findByRole('button', { name: /Single episode.*100 Beans/ }));
  await user.click(await screen.findByRole('button', { name: 'Simulate delayed confirmation' }));
  await screen.findByText(/Your order is processing/);
  await user.click(screen.getByRole('button', { name: 'Close' }));
  await select();
  await screen.findByRole('button', { name: 'Check existing order' });
  expect(screen.getByRole('button', { name: /Single episode.*100 Beans/ }).hasAttribute('disabled')).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Complete delayed preview payment' }));
  await waitFor(() => expect(player.switch).toHaveBeenCalledTimes(1));
  expect(create).toHaveBeenCalledTimes(1);
});

it('an ended event can open choices but never auto-shows a rewarded ad', async () => {
  const user = userEvent.setup(); const result = page('/playlet/theater?id=1');
  await waitFor(() => expect(player.hook.mock.calls.some(([, e]) => e?.episodeNumber === 1)).toBe(true));
  player.ended = 1;
  result.rerender(view('/playlet/theater?id=1'));
  expect(await screen.findByRole('dialog', { name: 'Unlock episode 2' })).toBeTruthy();
  expect(screen.queryByRole('dialog', { name: 'Preview rewarded ad' })).toBeNull();
  expect(player.switch).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Close' }));
});

it('dialog keyboard stays inside the dialog and a denied access never reaches the player', async () => {
  const user = userEvent.setup(); page('/playlet/theater?id=1&seq=2');
  const dialog = await screen.findByRole('dialog', { name: 'Unlock episode 2' });
  await screen.findByRole('button', { name: /Single episode/ });
  await user.tab(); expect(dialog.contains(document.activeElement)).toBe(true);
  await user.keyboard('{ArrowDown}'); expect(player.switch).not.toHaveBeenCalled();
  expect(within(dialog).getByRole('button', { name: 'Watch an ad · unlock this episode' }).hasAttribute('disabled')).toBe(true);
  expect(player.hook.mock.calls.every(([, episode]) => episode === undefined)).toBe(true);
});

it('does not commit a failed playNext or a response that resolves after route unmount', async () => {
  const user = userEvent.setup(); const result = page('/playlet/theater?id=1');
  await waitFor(() => expect(player.hook.mock.calls.some(([, e]) => e?.episodeNumber === 1)).toBe(true));
  const original = catalog.getEpisodeAccess;
  let resolve!: (response: Awaited<ReturnType<typeof original>>) => void;
  vi.spyOn(catalog, 'getEpisodeAccess').mockImplementation((id, seq) => seq === 2
    ? new Promise(done => { resolve = done; }) : original(id, seq));
  await user.click(screen.getByRole('button', { name: /Drama · 3 Episodes/ }));
  await user.click(screen.getByRole('button', { name: 'Episode 2, locked' }));
  result.unmount();
  await act(async () => resolve({ access: 'unlocked', episode: { seq: 2, title: 'EP2', locked: false,
    vid: 'v2', album_id: 'a', episode_id: 'e2' } }));
  expect(player.switch).not.toHaveBeenCalled();
});
