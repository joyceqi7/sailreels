import { useNavigate } from 'react-router-dom';
import type { DramaSummary } from '../types/drama';

interface DramaCardProps {
  drama: DramaSummary;
  featured?: boolean;
  /** Hover/focus intent can replace the MANUAL preload target before click. */
  onPreloadIntent?: () => void;
}

export function DramaCard({
  drama,
  featured = false,
  onPreloadIntent,
}: DramaCardProps) {
  const navigate = useNavigate();
  return (
    <button
      className={featured ? 'drama-card featured-card' : 'drama-card'}
      onPointerEnter={onPreloadIntent}
      onFocus={onPreloadIntent}
      onPointerDown={onPreloadIntent}
      onClick={() => navigate(`/playlet/detail?id=${encodeURIComponent(drama.id)}`)}
    >
      <span className="cover-frame">
        {drama.cover ? <img src={drama.cover} alt="" loading={featured ? 'eager' : 'lazy'} decoding="async" /> : null}
      </span>
      <span className="card-copy">
        <strong>{drama.title}</strong>
        <small>{drama.subtitle}</small>
      </span>
    </button>
  );
}
