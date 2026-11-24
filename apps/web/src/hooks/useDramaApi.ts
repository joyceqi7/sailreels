import { useEffect, useState } from 'react';
import { mapDrama, mapDramaSummary, type CatalogDramaDetail } from '../api/catalog-adapters';
import { getDramaDetail, getDramaList } from '../api/catalog';
import type { DramaSummary } from '../types/drama';

interface ApiState<T> {
  data?: T;
  loading: boolean;
  error?: string;
}

export function useDramaList(): ApiState<DramaSummary[]> {
  const [state, setState] = useState<ApiState<DramaSummary[]>>({ loading: true });

  useEffect(() => {
    let active = true;
    getDramaList()
      .then((data) => {
        if (active) setState({ data: data.map(mapDramaSummary), loading: false });
      })
      .catch((error: unknown) => {
        if (active) setState({ loading: false, error: 'Unable to load dramas. Please try again.' });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}

export function useDramaDetail(dramaId: string): ApiState<CatalogDramaDetail> {
  const [state, setState] = useState<ApiState<CatalogDramaDetail>>({ loading: true });

  useEffect(() => {
    let active = true;
    setState({ loading: true });
    getDramaDetail(dramaId)
      .then((data) => {
        if (active) setState({ data: mapDrama(data), loading: false });
      })
      .catch((error: unknown) => {
        if (active) setState({ loading: false, error: 'Unable to load this drama. Please try again.' });
      });
    return () => {
      active = false;
    };
  }, [dramaId]);

  return state;
}
