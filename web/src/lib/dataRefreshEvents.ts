/**
 * Cross-page refresh bus for live stats (dataset counts, matchrate,
 * overview readiness, etc.).
 *
 * Mutations that change shared eval data should call ``notifyDataChanged`` so
 * long-lived views (Sidebar, open Results) soft-refresh without a full reload.
 */

export const POI_DATA_CHANGED = "poi:data-changed";

export type DataChangedDetail = {
  /** Optional hint for listeners (e.g. "reconcile", "datasets", "run"). */
  source?: string;
};

/** Broadcast that shared evaluation data may have changed. */
export function notifyDataChanged(source?: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<DataChangedDetail>(POI_DATA_CHANGED, {
      detail: { source },
    }),
  );
}
