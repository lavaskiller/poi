import { useEffect, useRef } from "react";
import { POI_DATA_CHANGED } from "./dataRefreshEvents";

/**
 * Call ``refresh`` when the tab is focused/visible again, or when
 * ``poi:data-changed`` is dispatched after a mutation.
 *
 * Does not fire on mount — callers load once via useAsync already.
 */
export function useRefreshOnFocus(
  refresh: () => void,
  opts: { enabled?: boolean; debounceMs?: number } = {},
): void {
  const enabled = opts.enabled !== false;
  const debounceMs = opts.debounceMs ?? 400;
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const lastRef = useRef(0);

  useEffect(() => {
    if (!enabled) return;

    const fire = () => {
      const now = Date.now();
      if (now - lastRef.current < debounceMs) return;
      lastRef.current = now;
      refreshRef.current();
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") fire();
    };

    window.addEventListener("focus", fire);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener(POI_DATA_CHANGED, fire);
    return () => {
      window.removeEventListener("focus", fire);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener(POI_DATA_CHANGED, fire);
    };
  }, [enabled, debounceMs]);
}
