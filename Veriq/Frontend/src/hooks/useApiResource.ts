import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncResource<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Small loading/error/data hook. The loader must be memoized with
 * `useCallback`; changing it (or the explicit deps) reloads the resource.
 */
export function useApiResource<T>(loader: () => Promise<T>): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const requestId = useRef(0);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    const current = ++requestId.current;
    let active = true;
    setLoading(true);
    setError(null);

    loader()
      .then((result) => {
        if (active && current === requestId.current) {
          setData(result);
        }
      })
      .catch((cause: unknown) => {
        if (active && current === requestId.current) {
          setError(cause instanceof Error ? cause.message : 'Request failed');
        }
      })
      .finally(() => {
        if (active && current === requestId.current) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [loader, tick]);

  return { data, loading, error, reload };
}
