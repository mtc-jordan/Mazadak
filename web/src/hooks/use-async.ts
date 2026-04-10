"use client";

import { useState, useCallback, useEffect, useRef } from "react";

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Generic async data fetching hook.
 * Calls fetcher on mount and exposes refetch.
 */
export function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
) {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  });
  const mountedRef = useRef(true);

  const execute = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetcher();
      if (mountedRef.current) {
        setState({ data, loading: false, error: null });
      }
    } catch (e: any) {
      if (mountedRef.current) {
        setState({ data: null, loading: false, error: e?.message ?? "Error" });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    mountedRef.current = true;
    execute();
    return () => {
      mountedRef.current = false;
    };
  }, [execute]);

  return { ...state, refetch: execute };
}
