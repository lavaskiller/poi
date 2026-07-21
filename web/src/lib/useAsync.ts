import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "error"; data: null; error: Error }
  | { status: "ready"; data: T; error: null };

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading", data: null, error: null });

  const run = useCallback(() => {
    let alive = true;
    setState({ status: "loading", data: null, error: null });
    fn()
      .then((data) => alive && setState({ status: "ready", data, error: null }))
      .catch((error) => alive && setState({ status: "error", data: null, error }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);

  return { ...state, reload: run };
}
