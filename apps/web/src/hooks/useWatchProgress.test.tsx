// @vitest-environment jsdom
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useWatchProgress } from './useWatchProgress';
import { saveProgress, type Progress } from '../api/account';
import type { EpisodeSource } from '../types/drama';
vi.mock('../api/account', () => ({ saveProgress: vi.fn() }));
const first: EpisodeSource = { id: '1:1', episodeNumber: 1, title: '', description: '', albumId: 'a1', vid: 'v1', episodeId: 'e1' };
const second = { ...first, id: '1:2', episodeNumber: 2, vid: 'v2', episodeId: 'e2' };
const seek = vi.fn().mockReturnValue(true);
function Harness({ episode = first, time = 0, ready = true, switching = false, saved = null }: {
  episode?: EpisodeSource; time?: number; ready?: boolean; switching?: boolean; saved?: Progress | null;
}) {
  useWatchProgress('1', episode, time, 100, ready, switching, saved, seek); return null;
}
beforeEach(() => { vi.useFakeTimers(); seek.mockClear(); vi.mocked(saveProgress).mockReset().mockResolvedValue({} as Progress); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
it('throttles updates and flushes the previous episode before storing its successor', async () => {
  const result = render(<Harness time={12} />);
  result.rerender(<Harness time={18} />);
  expect(saveProgress).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(10_000));
  expect(saveProgress).toHaveBeenLastCalledWith('1', 1, 18);
  result.rerender(<Harness time={24} />);
  result.rerender(<Harness episode={second} time={0} />);
  expect(saveProgress).toHaveBeenLastCalledWith('1', 1, 24);
  result.rerender(<Harness episode={second} time={6} />); result.unmount();
  expect(saveProgress).toHaveBeenLastCalledWith('1', 2, 6);
});
it('does not overwrite progress for loading/locked or switching media', async () => {
  const result = render(<Harness ready={false} time={0} />);
  await act(() => vi.advanceTimersByTimeAsync(10_000)); expect(saveProgress).not.toHaveBeenCalled();
  result.rerender(<Harness time={20} />); result.rerender(<Harness time={0} switching />);
  result.unmount(); expect(saveProgress).toHaveBeenLastCalledWith('1', 1, 20);
});
it('restores position only after the authorized first frame and preserves backward seeks', async () => {
  const saved = { drama_id: 1, last_seq: 1, position_seconds: 42, updated_at: new Date().toISOString() };
  const result = render(<Harness saved={saved} ready={false} />); expect(seek).not.toHaveBeenCalled();
  result.rerender(<Harness saved={saved} />); expect(seek).toHaveBeenCalledWith(42);
  result.rerender(<Harness saved={saved} time={42} />);
  result.rerender(<Harness saved={saved} time={12} />);
  result.unmount(); expect(saveProgress).toHaveBeenLastCalledWith('1', 1, 12);
});
