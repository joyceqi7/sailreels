// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SquarePage } from './SquarePage';
vi.mock('../hooks/useDramaApi', () => ({ useDramaList: () => ({ loading: false, data: Array.from({ length: 12 }, (_, i) => ({ id: String(i + 1), title: `Story ${i + 1}`, category: 'Popular', cover: '', subtitle: '', episodeCount: 10 })) }) }));
vi.mock('../api/access', () => ({ loadPlayableEpisode: vi.fn().mockRejectedValue(new Error('No preview')) }));
vi.mock('../plugins/minis-player', () => ({ preloadDramaEpisode: vi.fn() }));
vi.mock('../router/lazy-pages', () => ({ preloadTheaterPageCode: vi.fn() }));
afterEach(cleanup);
it('makes the complete catalog reachable without duplicate cards inside a section and supports search', async () => {
  render(<MemoryRouter><SquarePage /></MemoryRouter>);
  const trending = screen.getByRole('region', { name: 'Trending' });
  expect(within(trending).getAllByRole('button')).toHaveLength(12);
  expect(within(trending).getAllByText('Story 1')).toHaveLength(1);
  await userEvent.type(screen.getByRole('searchbox'), 'Story 12');
  const results = screen.getByRole('region', { name: 'Search results' });
  expect(within(results).getAllByRole('button')).toHaveLength(1);
  expect(within(results).getByText('Story 12')).toBeTruthy();
});

it('keeps the header shortcuts and the four-tab bottom nav', () => {
  render(<MemoryRouter initialEntries={['/playlet/square']}><SquarePage /></MemoryRouter>);
  const header = document.querySelector('.discovery-header');
  expect(header).toBeTruthy();
  expect(within(header as HTMLElement).getByRole('searchbox', { name: 'Search dramas' })).toBeTruthy();
  expect(within(header as HTMLElement).getByRole('link', { name: 'Your profile' }).getAttribute('href')).toBe('/playlet/profile');
  expect(within(header as HTMLElement).getByRole('link', { name: 'History' }).getAttribute('href')).toBe('/playlet/history');
  const nav = screen.getByRole('navigation', { name: 'Primary navigation' });
  const tabs = [
    ['Home', '/playlet/square'],
    ['For You', '/playlet/foryou'],
    ['History', '/playlet/history'],
    ['Profile', '/playlet/profile'],
  ] as const;
  expect(within(nav).getAllByRole('link')).toHaveLength(tabs.length);
  for (const [label, href] of tabs) {
    expect(within(nav).getByRole('link', { name: label }).getAttribute('href')).toBe(href);
  }
  expect(within(nav).getByRole('link', { name: 'Home' }).getAttribute('aria-current')).toBe('page');
});
