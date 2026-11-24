import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';
import { createServer as createHttpServer } from 'node:http';

let server;
let client;
let adapters;
let playback;

before(async () => {
  // Compile the actual TS modules with the existing Vite dependency.
  // No browser, backend, SDK or external network is required.
  server = await createServer({
    optimizeDeps: { noDiscovery: true, include: [] },
    define: { 'import.meta.env.VITE_API_MODE': JSON.stringify('mock') },
    server: { middlewareMode: true, hmr: { server: createHttpServer() }, watch: null },
    appType: 'custom',
  });
  client = await server.ssrLoadModule('/src/api/catalog.ts');
  adapters = await server.ssrLoadModule('/src/api/catalog-adapters.ts');
  playback = await server.ssrLoadModule('/src/api/access.ts');
});

after(async () => { await server?.close(); });

test('catalog is the backend metadata array, with no playback identifiers', async () => {
  const catalog = await client.getDramaList();
  assert.ok(Array.isArray(catalog));
  assert.equal(catalog.length, 2);
  for (const item of catalog) {
    assert.deepEqual(Object.keys(item).sort(), [
      'id', 'title', 'description', 'cover_url', 'total_episodes',
      'free_episodes', 'unlock_price_beans',
    ].sort());
    assert.ok(Number.isInteger(item.id) && item.id > 0);
    assert.equal(item.free_episodes, 1);
  }
  assert.equal(new Set(catalog.map(item => item.id)).size, catalog.length);
});

test('backend metadata maps to a card without inventing playable episodes', () => {
  const card = adapters.mapDramaSummary({
    id: 47,
    title: 'Contract example',
    description: 'From the backend',
    cover_url: '',
    total_episodes: 12,
    free_episodes: 1,
    unlock_price_beans: 100,
  });
  assert.equal(card.id, '47');
  assert.equal(card.subtitle, 'From the backend');
  assert.equal(card.episodeCount, 12);
  assert.equal(card.cover, '');
  assert.equal(card.category, 'Popular');
  assert.equal(card.preloadEpisode, undefined);
  assert.equal(card.episodes, undefined);
});

test('every card opens metadata with all episode numbers but no media identities', async () => {
  for (const item of await client.getDramaList()) {
    const card = adapters.mapDramaSummary(item);
    const response = await client.getDramaDetail(card.id);
    const detail = adapters.mapDrama(response);
    assert.equal(detail.id, card.id);
    assert.equal(detail.title, card.title);
    assert.equal(detail.cover, card.cover);
    assert.equal(detail.episodes.length, item.total_episodes);
  }
  const detail = adapters.mapDrama(await client.getDramaDetail('1'));
  assert.deepEqual(detail.episodes.map(item => item.episodeNumber), [1, 2, 3]);
  for (const episode of detail.episodes) {
    assert.equal(episode.albumId, undefined);
    assert.equal(episode.episodeId, undefined);
    assert.equal(episode.vid, undefined);
  }
});

test('callers cannot mutate subsequent mock catalog or detail responses', async () => {
  const first = await client.getDramaList();
  first[0].title = 'changed';
  first.splice(1);
  const next = await client.getDramaList();
  assert.equal(next.length, 2);
  assert.notEqual(next[0].title, 'changed');
  const detail = await client.getDramaDetail('1');
  detail.title = 'changed';
  assert.notEqual((await client.getDramaDetail('1')).title, 'changed');
});

test('an unknown drama fails instead of opening a different fixture', async () => {
  await assert.rejects(client.getDramaDetail('999'), /was not found/);
});

test('mock access matches the backend seed: first free, second and third locked', async () => {
  const first = await playback.loadPlayableEpisode('1', 1);
  assert.equal(first.albumId, '7667061213232384021');
  assert.equal(first.episodeId, '7667063938195015688');
  assert.equal(first.id, '1:1');
  for (const seq of [2, 3]) {
    assert.deepEqual(await client.getEpisodeAccess('1', seq), { access: 'locked', episode: null, unlock_price_beans: 100 });
    await assert.rejects(playback.loadPlayableEpisode('1', seq), playback.EpisodeLockedError);
  }
});

for (const access of ['free', 'unlocked', 'subscribed']) {
  test(`only a complete ${access} grant supplies playback identities`, async () => {
    const response = await client.getEpisodeAccess('1', 1);
    response.access = access;
    assert.equal(playback.resolveEpisodeAccess(response, '1', 1).episodeId, '7667063938195015688');
  });
}

test('locked response is denied even if it accidentally contains media IDs', async () => {
  const response = await client.getEpisodeAccess('1', 1);
  response.access = 'locked';
  assert.throws(() => playback.resolveEpisodeAccess(response, '1', 1), playback.EpisodeLockedError);
});

test('unknown, incomplete, wrong-episode and numeric-media-ID responses fail closed', async () => {
  const response = await client.getEpisodeAccess('1', 1);
  const episode = response.episode;
  const invalid = [null, {}, { ...response, access: 'paid' }, { ...response, episode: null },
    ...[{ locked: true }, { seq: 2 }, { album_id: null }, { episode_id: 7667063938195015688 }, { vid: '' }]
      .map(patch => ({ ...response, episode: { ...episode, ...patch } }))];
  for (const value of invalid) assert.throws(() => playback.resolveEpisodeAccess(value, '1', 1));
});

test('access mocks do not share mutable state and invalid targets cannot fall back', async () => {
  const first = await client.getEpisodeAccess('1', 1);
  first.episode.vid = 'changed';
  assert.notEqual((await client.getEpisodeAccess('1', 1)).episode.vid, 'changed');
  for (const id of ['../1', 'abc', '0', '1.2']) await assert.rejects(client.getEpisodeAccess(id, 1));
  for (const seq of [0, -1, 1.5, 4]) await assert.rejects(client.getEpisodeAccess('1', seq));
});
