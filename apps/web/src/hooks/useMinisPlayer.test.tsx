// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { useMinisPlayer } from './useMinisPlayer';
import type { Drama, EpisodeSource } from '../types/drama';

const first: EpisodeSource = { id: '1:1', episodeNumber: 1, title: 'First', description: '',
  albumId: '7667061213232384021', episodeId: '7667063938195015688', vid: 'first-authorized-vid' };
const second: EpisodeSource = { ...first, id: '1:2', episodeNumber: 2,
  episodeId: '7667063938195032072', vid: 'second-authorized-vid' };
const configs: Record<string, unknown>[] = [];
const instances: FakePlayer[] = [];
class FakePlayer {
  static prepare = vi.fn();
  static setPreloadScene = vi.fn();
  static setPreloadList = vi.fn();
  static setMediaInfoCacheConfig = vi.fn();
  player = { media: document.createElement('video') };
  handlers = new Map<string, (...args: unknown[]) => void>();
  playNext = vi.fn().mockResolvedValue(undefined);
  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn(); destroy = vi.fn();
  on = (event: string, handler: (...args: unknown[]) => void) => { this.handlers.set(event, handler); };
  once = vi.fn();
  constructor(config: Record<string, unknown>) { configs.push(config); instances.push(this); }
}
afterEach(() => {
  cleanup(); configs.length = 0; instances.length = 0;
  delete (window as Window & { TTMinis?: unknown }).TTMinis;
});

it('waits for an authorized source, creates one SDK Player, reuses playNext, and destroys on unmount', async () => {
  Object.defineProperty(window, 'TTMinis', { configurable: true, value: { getPlayer: () => FakePlayer } });
  let current!: ReturnType<typeof useMinisPlayer>;
  function Harness({ episode }: { episode?: EpisodeSource }) {
    const drama: Drama = { id: '1', title: 'Test', subtitle: '', category: 'Popular', cover: '',
      episodeCount: 3, episodes: episode ? [episode] : [] };
    current = useMinisPlayer(drama, episode);
    return <div ref={current.rootRef} />;
  }
  const result = render(<Harness />);
  expect(instances).toHaveLength(0);
  result.rerender(<Harness episode={first} />);
  await waitFor(() => expect(instances).toHaveLength(1));
  expect(configs[0].vid).toBe(first.vid);
  expect(configs[0].episodeId).toBe(first.episodeId);
  expect(configs[0]).not.toHaveProperty('url'); expect(configs[0]).not.toHaveProperty('playList');
  const instance = instances[0];
  await act(async () => { expect(await current.switchEpisode(second)).toBe(true); });
  result.rerender(<Harness episode={second} />);
  expect(instances).toHaveLength(1);
  expect(instance.playNext).toHaveBeenCalledTimes(1);
  expect(instance.playNext.mock.calls[0][0]).toMatchObject({ vid: second.vid, episodeId: second.episodeId });
  act(() => instance.handlers.get('ended')?.());
  expect(current.endedCount).toBe(1);
  instance.playNext.mockRejectedValueOnce(new Error('SDK switch failed'));
  await act(async () => { expect(await current.switchEpisode(first)).toBe(false); });
  expect(current.isSwitching).toBe(false);
  expect(current.status).toBe('error');
  expect(instance.destroy).not.toHaveBeenCalled();
  result.unmount();
  expect(instance.destroy).toHaveBeenCalledTimes(1);
});

it('starts playback even when optional preload initialization never completes', async () => {
  FakePlayer.prepare.mockImplementation(() => new Promise(() => {}));
  Object.defineProperty(window, 'TTMinis', { configurable: true, value: { getPlayer: () => FakePlayer } });
  function Harness() {
    const state = useMinisPlayer({ id: '2', title: 'Direct entry', subtitle: '', category: 'Popular', cover: '', episodeCount: 1, episodes: [first] }, first);
    return <div ref={state.rootRef} />;
  }
  render(<Harness />);
  await waitFor(() => expect(instances).toHaveLength(1));
  expect(configs[0].vid).toBe(first.vid);
});
