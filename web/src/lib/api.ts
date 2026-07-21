// Thin typed wrapper around the Python backend (server.py) /api routes.
// In dev, Vite proxies /api → http://localhost:8420 (see vite.config.ts).

export interface OverviewSource {
  key: string;
  count: number;
  label: string;
  known?: boolean;
}

export interface Overview {
  data_state: string; // "ready" | "empty" | ...
  csv_present: boolean;
  total: number;
  n_columns?: number;
  sources: OverviewSource[];
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export interface ReconcileCandidate {
  rank: number;
  name: string;
  distance?: number | null;
  category?: string;
}
export interface ReconcileCase {
  dataset: string;
  photo: string;
  image: string;
  gt: string;
  ocr: string;
  candidates: ReconcileCandidate[];
}
export interface ReconcileQueue {
  total_non_mapkit: number;
  done: number;
  remaining: number;
  cases: ReconcileCase[];
}

export const api = {
  overview: () => getJSON<Overview>("/api/overview"),

  /** GT↔MapKit reconciliation queue — NON_MAPKIT cases with candidate lists. */
  reconcileQueue: () => getJSON<ReconcileQueue>("/api/gt/reconcile"),

  /** Persist a manual match (chosen candidate name, or "" for not-in-list). */
  async reconcileSave(c: { dataset: string; photo: string; gt: string; chosen: string }): Promise<{
    ok: boolean;
    done: number;
    remaining: number;
  }> {
    const res = await fetch("/api/gt/reconcile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(c),
    });
    const data = (await res.json().catch(() => ({}))) as { ok?: boolean; done?: number; remaining?: number; message?: string };
    if (!res.ok || data.ok === false) throw new Error(data.message || `/api/gt/reconcile → HTTP ${res.status}`);
    return { ok: true, done: data.done ?? 0, remaining: data.remaining ?? 0 };
  },

  /** Inject the bundled onboarding seed (initial dataset + baseline runs). */
  async seed(preset: string): Promise<{ ok: boolean; message?: string }> {
    const res = await fetch("/api/seed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset }),
    });
    const data = (await res.json().catch(() => ({}))) as { ok?: boolean; message?: string };
    if (!res.ok) throw new Error(data.message || `/api/seed → HTTP ${res.status}`);
    return { ok: data.ok ?? true, message: data.message };
  },
};

/** True when the backend has no dataset loaded yet (first-run / onboarding). */
export function isEmpty(o: Overview): boolean {
  return !o.csv_present || o.data_state === "empty" || (o.sources?.length ?? 0) === 0;
}
