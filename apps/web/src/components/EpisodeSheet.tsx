import { useEffect, useMemo, useState } from 'react';
import type { CatalogDramaDetail } from '../api/catalog-adapters';
import { Dialog } from './Dialog';

interface Props {
  drama: CatalogDramaDetail;
  locked?: Set<number>;
  current: number;
  open: boolean;
  onClose: () => void;
  onSelect: (index: number) => void;
}

export function EpisodeSheet({ drama, current, open, onClose, onSelect, locked }: Props) {
  const pages = useMemo(
    () => {
      const total = drama.episodes.length;
      if (total > 62) {
        return [
          { start: 0, end: Math.min(24, total) },
          { start: 24, end: Math.min(48, total) },
          { start: 48, end: Math.min(62, total) },
          { start: 62, end: total },
        ].filter((range) => range.start < range.end);
      }
      return Array.from({ length: Math.ceil(total / 24) }, (_, index) => ({
        start: index * 24,
        end: Math.min((index + 1) * 24, total),
      }));
    },
    [drama.episodes.length],
  );
  const currentPage = () => Math.max(0, pages.findIndex((page) => current >= page.start && current < page.end));
  const [pageIndex, setPageIndex] = useState(currentPage);

  useEffect(() => {
    if (open) setPageIndex(currentPage());
  }, [current, open, pages]);

  if (!open) return null;
  const page = pages[pageIndex] ?? pages[0];
  const visibleEpisodes = drama.episodes.slice(page.start, page.end);

  return (
    <Dialog title="Choose episode" onClose={onClose}>
        <p>{drama.title}</p>
        <div className="episode-ranges" role="tablist" aria-label="Episode ranges">
          {pages.map((item, index) => (
            <button
              key={item.start}
              role="tab"
              aria-selected={pageIndex === index}
              onClick={() => setPageIndex(index)}
            >
              {item.start + 1}-{item.end}
            </button>
          ))}
        </div>
        <div className="episode-grid">
          {visibleEpisodes.map((item, offset) => {
            const index = page.start + offset;
            return (
              <button key={item.id} aria-label={`Episode ${item.episodeNumber}${locked?.has(item.episodeNumber) ? ', locked' : ''}`} className={index === current ? 'is-current' : ''} onClick={() => { onSelect(index); onClose(); }}>
                {index === current && <i aria-hidden="true"><span /><span /><span /></i>}
                <b>{index + 1}</b>
                {locked?.has(item.episodeNumber) && <small aria-hidden="true">🔒</small>}
              </button>
            );
          })}
        </div>
        {/* <footer className="sheet-footer"><div className="sheet-home-indicator" aria-hidden="true" /></footer> */}
    </Dialog>
  );
}
