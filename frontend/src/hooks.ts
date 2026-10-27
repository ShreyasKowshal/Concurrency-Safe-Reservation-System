import { useCallback, useEffect, useRef, useState } from "react";
import { isAbort } from "./api/client";

// Commands may commit after navigation; keep their intent in the API client, but
// ignore component callbacks once their originating screen has gone away.
export function useActive() {
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  return active;
}

export function useResource<T>(
  key: string,
  loader: (signal: AbortSignal) => Promise<T>,
) {
  const load = useRef(loader);
  load.current = loader;
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const [state, setState] = useState<{
    key: string;
    data?: T;
    error?: unknown;
    loading: boolean;
  }>({ key, loading: true });
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const ticket = ++sequence.current;
    setState((previous) => ({
      key,
      data: previous.key === key ? previous.data : undefined,
      loading: true,
    }));
    try {
      const data = await load.current(next.signal);
      if (!next.signal.aborted && ticket === sequence.current)
        setState({ key, data, loading: false });
    } catch (error) {
      if (
        !next.signal.aborted &&
        ticket === sequence.current &&
        !isAbort(error)
      )
        setState({ key, error, loading: false });
    }
  }, [key]);
  useEffect(() => {
    void refresh();
    return () => {
      ++sequence.current;
      controller.current?.abort();
    };
  }, [refresh]);
  return {
    ...(state.key === key
      ? state
      : { key, loading: true, data: undefined, error: undefined }),
    refresh,
  };
}
