// Thin typed wrapper around the Python backend (server.py) /api routes.
// In dev, Vite proxies /api → http://localhost:8420 (see vite.config.ts).

export interface OverviewSource {
  key: string;
  count: number;
  label: string;
  known?: boolean;
}

export interface OverviewCountry {
  key: string;
  count: number;
  flag?: string;
}

export interface SchemaField {
  group: string; // human label, e.g. "photo_url / photo"
  role_key: string; // "in" | "gt" | "bl" | "mt"
  role_label: string;
  fill: number; // rows with this field present
  cols: string[];
  desc?: string;
}

export interface Overview {
  data_state: string; // "ready" | "empty" | ...
  csv_present: boolean;
  total: number;
  n_columns?: number;
  sources: OverviewSource[];
  countries?: OverviewCountry[];
  datasets?: string[];
  photo_present?: number;
  gt_present?: number;
  config_warnings?: string[];
  schema?: SchemaField[];
}

export interface Run {
  name: string;
  version: number;
  scope: string;
  accuracy_pct: number | null;
  accuracy_canonical_pct: number | null;
  n_eligible: number;
  correct: number;
  created_at: string;
  runtime?: string;
}

export interface RunCase {
  dataset: string;
  photo: string;
  gt: string;
  prediction: string;
  correct: boolean;
  correct_canonical: boolean;
  match_kind: string;
  photo_url?: string;
  context?: {
    input_place_name?: string;
    category?: string;
    city?: string;
    country?: string;
    ocr_text?: string;
  };
}

export interface RunDetail extends Run {
  mode?: string;
  cases: RunCase[];
}

export interface MatchRate {
  eligible: number;
  evaluated: number;
  selection_failure: number;
  search_failure: number;
  miss: number;
  counts: Record<string, number>;
}

export interface CaseCandidate {
  rank: number;
  name: string;
  distance?: number | null;
  category?: string;
}
export interface CaseDetail {
  dataset: string;
  photo: string;
  image: string;
  gt: string;
  gt_mapkit: string;
  prediction: string;
  reason: string;
  match_kind: string;
  correct: boolean;
  run: { name: string; version: number } | null;
  lat: string;
  lon: string;
  signals: { gps: string; ocr: string; nearby: string; category: string };
  candidates: CaseCandidate[];
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
  lat: string;
  lon: string;
  ocr: string;
  candidates: ReconcileCandidate[];
}

export interface ProbeResult {
  ok: boolean;
  lat?: number;
  lon?: number;
  candidates: ReconcileCandidate[];
  message?: string;
}
export interface ReconcileQueue {
  total_non_mapkit: number;
  done: number;
  remaining: number;
  no_candidate: number;
  cases: ReconcileCase[];
}

export const api = {
  overview: () => getJSON<Overview>("/api/overview"),

  runs: () => getJSON<{ runs: Run[] }>("/api/runs"),

  run: (name: string, version: number) =>
    getJSON<{ run: RunDetail }>(
      `/api/runs?name=${encodeURIComponent(name)}&version=${encodeURIComponent(version)}`,
    ),

  matchrate: () => getJSON<MatchRate>("/api/matchrate"),

  case: (dataset: string, photo: string) =>
    getJSON<CaseDetail>(
      `/api/case?dataset=${encodeURIComponent(dataset)}&photo=${encodeURIComponent(photo)}`,
    ),

  /** Live MapKit nearby query for a coordinate (Investigate). Slow (~20–30s). */
  async mapkitProbe(lat: number, lon: number): Promise<ProbeResult> {
    const res = await fetch("/api/mapkit/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon }),
    });
    return (await res.json()) as ProbeResult;
  },

  /** GT↔MapKit reconciliation queue — NON_MAPKIT cases with candidate lists. */
  reconcileQueue: () => getJSON<ReconcileQueue>("/api/gt/reconcile"),

  /** Persist a match: a candidate picked from the list, a manually typed place
   *  (manual=true, for no-candidate cases), or "" for not-in-MapKit. */
  async reconcileSave(c: {
    dataset: string;
    photo: string;
    gt: string;
    chosen: string;
    manual?: boolean;
  }): Promise<{ ok: boolean; done: number; remaining: number }> {
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
