import type { DramaDTO, EpisodeDTO } from './types';

type EpisodeIdentity = Pick<
  EpisodeDTO,
  'vid' | 'album_id' | 'episode_id' | 'poster_url'
>;

const DRAMA_TWO_EPISODES: EpisodeIdentity[] = [
  {
    // Portrait source. The Player's fill mode handles its aspect ratio.
    vid: 'v18b3bgm0018d9hf3tatgd69034qlok0',
    album_id: '7665126538443196436',
    episode_id: '7665648457684502549',
    poster_url: '/posters/drama-02-1.jpg',
  },
  {
    vid: 'v25b3bgm0018d9hnhvitgd691neud81g',
    album_id: '7665126538443196436',
    episode_id: '7665648457684518933',
    poster_url: '/posters/drama-02-2.jpg',
  },
  {
    vid: 'v18b3bgm0018d9hni6atgd606diraqu0',
    album_id: '7665126538443196436',
    episode_id: '7665648457684535317',
    poster_url: '/posters/drama-02-3.jpg',
  },
  // {
  //   vid: 'v25b3bgm0018d9g6i7atgd62dtifi5h0',
  //   album_id: '7665126538443196436',
  //   episode_id: '7665127169326467092',
  // }
];

const DRAMA_THREE_EPISODES: EpisodeIdentity[] = [
  {
    vid: 'v25b3bgm0018d9jgcu2tgd62dtifvgc0',
    album_id: '7667061213232384021',
    episode_id: '7667063938195015688',
    poster_url: '/posters/drama-03-1.jpg',
  },
  {
    vid: 'v25b3bgm0018d9jgdaqtgd63istgth3g',
    album_id: '7667061213232384021',
    episode_id: '7667063938195032072',
    poster_url: '/posters/drama-03-2.jpg',
  },
  {
    vid: 'v18b3bgm0018d9jgdjatgd606dirdp0g',
    album_id: '7667061213232384021',
    episode_id: '7667063938195048456',
    poster_url: '/posters/drama-03-3.jpg',
  },
];

// const DRAMA_TWO_EPISODES: EpisodeIdentity[] = [
//   {
//     // Portrait source. The Player's fill mode handles its aspect ratio.
//     vid: 'v18b3bgm0018d9hf3tatgd69034qlok0',
//     album_id: '7665126538443196436',
//     episode_id: '7665652286249797653',
//   },
//   {
//     vid: 'v25b3bgm0018d9g6hritgd646irbs8rg',
//     album_id: '7665126538443196436',
//     episode_id: '7665127169326434324',
//   },
//   {
//     vid: 'v25b3bgm0018d9g6i2itgd6ep5fj2ik0',
//     album_id: '7665126538443196436',
//     episode_id: '7665127169326450708',
//   },
//   {
//     vid: 'v25b3bgm0018d9g6i7atgd62dtifi5h0',
//     album_id: '7665126538443196436',
//     episode_id: '7665127169326467092',
//   }
// ];

function indexEpisodeIdentities(
  episodes: EpisodeIdentity[],
): Partial<Record<number, Partial<EpisodeDTO>>> {
  return Object.fromEntries(
    episodes.map((episode, index) => [index + 1, episode]),
  );
}

function createMockDrama(
  dramaId: string,
  title: string,
  subtitle: string,
  coverUrl: string,
  category: DramaDTO['category'],
  episodeOverrides: Partial<Record<number, Partial<EpisodeDTO>>> = {},
  episodeCount = 74,
): DramaDTO {
  const albumId = `mock-album-${dramaId}`;
  const episodes = Array.from({ length: episodeCount }, (_, offset) => {
    const episodeNumber = offset + 1;
    const episode: EpisodeDTO = {
      episode_id: `mock-episode-${dramaId}-${episodeNumber}`,
      album_id: albumId,
      episode_number: episodeNumber,
      title: `Episode ${episodeNumber}`,
      description: episodeNumber === 1
        ? 'Sometimes the truth is hidden by where you stand.'
        : 'One day, we\'ll sail with the wind across the boundless sea.',
      vid: `mock-vid-${dramaId}-${episodeNumber}`,
      play_auth_token: '',
    };
    return { ...episode, ...episodeOverrides[episodeNumber] };
  });

  return {
    drama_id: dramaId,
    title,
    subtitle,
    category,
    // A drama card opens episode 1, so its default artwork must represent the
    // same VID. Keep coverUrl only as a compatibility fallback for incomplete
    // backend payloads.
    cover_url: episodes[0]?.poster_url ?? coverUrl,
    episode_count: episodes.length,
    episodes,
  };
}

function createDramaTwoMock(
  dramaId: string,
  title: string,
  subtitle: string,
  category: DramaDTO['category'],
): DramaDTO {
  return createMockDrama(
    dramaId,
    title,
    subtitle,
    '/posters/drama-02-1.jpg',
    category,
    indexEpisodeIdentities(DRAMA_TWO_EPISODES),
    DRAMA_TWO_EPISODES.length,
  );
}

function createDramaThreeMock(
  dramaId: string,
  title: string,
  subtitle: string,
  category: DramaDTO['category'],
): DramaDTO {
  return createMockDrama(
    dramaId,
    title,
    subtitle,
    '/posters/drama-03-1.jpg',
    category,
    indexEpisodeIdentities(DRAMA_THREE_EPISODES),
    DRAMA_THREE_EPISODES.length,
  );
}

/** Mock payloads deliberately use the same snake_case shape as the backend. */
export const MOCK_DRAMAS: DramaDTO[] = [
  createDramaTwoMock(
    'test',
    'test',
    'test-drama',
    'Popular',
  ),
  createDramaThreeMock(
    'test-NewEP1',
    'test-NewEP1',
    'test-drama', 
    'Popular',
  ),
];
