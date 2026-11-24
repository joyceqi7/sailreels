import { Link, useSearchParams } from 'react-router-dom';
import { useDramaDetail } from '../hooks/useDramaApi';
import { IAP_ENABLED } from '../monetization';

export function DetailPage() {
  const [params] = useSearchParams();
  const { data: drama, loading, error } = useDramaDetail(params.get('id') ?? '');
  return <main className="app-shell detail-page">
    <Link className="back-link" to="/playlet/square">‹ All dramas</Link>
    {loading ? <p className="page-state" role="status">Loading drama…</p> : error || !drama ?
      <div className="page-state" role="alert">{error ?? 'Drama not found.'}</div> : <>
      <div className="detail-hero">
        {drama.cover && <img src={drama.cover} alt="" />}
        <div><h1>{drama.title}</h1><p>{drama.episodeCount} episodes</p>
          <p>{drama.freeEpisodes} free · {IAP_ENABLED ? `${drama.unlockPriceBeans} Beans per paid episode`
            : 'unlock the rest with a short ad'}</p></div>
      </div>
      <p className="detail-synopsis">{drama.subtitle || 'Explore the story, one episode at a time.'}</p>
      {drama.episodes.length ? <>
        <Link className="primary-action" to={`/playlet/theater?id=${encodeURIComponent(drama.id)}`}>Start watching</Link>
        <h2>Episodes</h2><p>{IAP_ENABLED ? 'Paid episodes require an unlock.' : 'Locked episodes unlock with a short ad.'}
          {' '}Your access is checked before each episode plays.</p>
        <div className="detail-episodes">{drama.episodes.map((episode) =>
          <Link key={episode.id} to={`/playlet/theater?id=${encodeURIComponent(drama.id)}&seq=${episode.episodeNumber}`}>
            {episode.episodeNumber}<small>{episode.episodeNumber <= drama.freeEpisodes ? 'Free' : 'Check access'}</small>
          </Link>)}</div>
      </> : <p>No episodes are available yet.</p>}
    </>}
  </main>;
}
