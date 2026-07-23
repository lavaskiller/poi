import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "error"; data: null; error: Error }
  | { status: "ready"; data: T; error: null };

/**
 * Load async data keyed by ``deps``.
 *
 * - ``reload()`` — hard refresh (loading flash; for explicit Retry).
 * - ``softReload()`` — background refresh; keeps previous data until the
 *   new result arrives, and keeps it on transient failure. Use for focus
 *   polling so UI counts don't freeze without a full-page spinner.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading", data: null, error: null });
  const genRef = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback((mode: "hard" | "soft" = "hard") => {
    const gen = ++genRef.current;
    if (mode === "hard") {
      setState({ status: "loading", data: null, error: null });
    }
    fnRef.current()
      .then((data) => {
        if (gen !== genRef.current) return;
        setState({ status: "ready", data, error: null });
      })
      .catch((error: unknown) => {
        if (gen !== genRef.current) return;
        const err = error instanceof Error ? error : new Error(String(error));
        setState((prev) => {
          // Soft refresh must not wipe a good screen on a blip.
          if (mode === "soft" && prev.status === "ready") return prev;
          return { status: "error", data: null, error: err };
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run("hard");
  }, [run]);

  const reload = useCallback(() => run("hard"), [run]);
  const softReload = useCallback(() => run("soft"), [run]);

  return {
    ...state,
    reload,
    softReload,
  };
}
