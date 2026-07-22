// Thin typed wrapper around the Python backend (server.py) /api routes.
// In dev, Vite proxies /api → http://localhost:8420 (see vite.config.ts).

export interface OverviewSource {
  key: string;
  count: number;
  label: string;
  known?: boolean;
  source_type?: string;
  desc?: string;
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

/** One selectable onboarding seed bundle discovered on disk. */
export interface SeedPreset {
  id: string;
  label: string;
  desc: string;
  /** false when the bundle exists but this preset's files are missing */
  available: boolean;
  rows: number;
  runs: number;
}
export interface SeedPresets {
  /** false when poi-data-seed/ is absent entirely (fresh clone) */
  bundle_present: boolean;
  /** repo-relative path where the bundle is expected (UI guidance) */
  seed_path: string;
  presets: SeedPreset[];
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
  fill?: Record<string, number>;
  fill_by_dataset?: Record<string, Record<string, number>>;
  total_by_dataset?: Record<string, number>;
}

export interface Run {
  name: string;
  version: number;
  scope: string;
  mode?: string;
  accuracy_pct: number | null;
  accuracy_canonical_pct: number | null;
  n_eligible: number;
  correct: number;
  correct_canonical?: number;
  created_at: string;
  runtime?: string | { device_class?: string; platform?: string };
  duration_ms?: number | null;
  params?: string[];
  candidate_limit?: number | null;
  evaluation_set_sha256?: string | null;
  match_kind_counts?: Record<string, number>;
  abstained?: number;
  errored?: number;
  metrics?: {
    by_dataset?: Record<
      string,
      { n?: number; correct?: number; accuracy?: number; accuracy_pct?: number }
    >;
  };
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
  reason?: string;
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
  n?: number;
  rank1?: number;
  top3?: number;
  top5?: number;
  top10?: number;
  top20?: number;
  top50?: number;
  rank1_rate?: number;
  top3_rate?: number;
  top5_rate?: number;
  top10_rate?: number;
  top20_rate?: number;
  top50_rate?: number;
  miss_rate?: number;
  counts: Record<string, number>;
  dataset?: string;
  mode?: string;
  /** Rows whose gt_mapkit was patched from Reconcile overrides at read time. */
  overrides_applied?: number;
  excluded_non_mapkit?: number;
}

export interface CaseCandidate {
  rank: number;
  name: string;
  distance?: number | null;
  category?: string;
  lat?: number | null;
  lon?: number | null;
  /** true when rank is within the linked run's candidate_limit */
  in_run_window?: boolean;
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
  /** Run's nearby top-K window (what predict() saw), when known */
  candidate_limit?: number | null;
  /** Full MapKit list size before display cap */
  candidate_total?: number;
  candidate_source?: string;
  lat: string;
  lon: string;
  signals: { gps: string; ocr: string; nearby: string; category: string };
  candidates: CaseCandidate[];
}

export interface SignalCoverageMetric {
  key: string;
  label: string;
  count: number;
  pct: number;
}

export interface SignalInfo {
  label: string;
  col: string | null;
  cols: string[];
  fill: number;
  empty: number;
  pct: number;
  processed: number | null;
  unprocessed: number | null;
  processed_pct: number | null;
  coverage_metrics: SignalCoverageMetric[];
  label_breakdown?: {
    total: number;
    items: { key: string; count: number; pct: number }[];
    excluded?: Record<string, number>;
  } | null;
  result_label: string;
  step: string | null;
  status: string;
}

export interface DatasetInfo {
  key: string;
  label: string;
  count: number;
  known: boolean;
  config_source: boolean;
  source_type: string;
  photo_dir: string | null;
  signals: Record<string, SignalInfo>;
}

export interface DatasetsResponse {
  datasets: DatasetInfo[];
  signals_meta: Record<string, unknown>;
}

export interface JobProgress {
  done?: number;
  total?: number;
  pct?: number;
  message?: string;
  eta_s?: number;
  [key: string]: unknown;
}

export interface Job {
  /** Prefer job_id (server field); id kept for older payloads. */
  id?: string;
  job_id?: string;
  step: string;
  status: string; // "running" | "done" | "error" | ...
  params?: Record<string, unknown>;
  started?: number | null;
  finished?: number | null;
  elapsed_s?: number | null;
  progress?: JobProgress | null;
  warnings?: unknown[];
  error?: string | null;
  result?: Record<string, unknown> | null;
  log_path?: string | null;
  log_tail?: string[];
}

/** One structured issue from /api/validate-upload-package. */
export interface ValidationIssue {
  code?: string;
  message?: string;
  row?: number;
  photo?: string;
  columns?: string[];
  photos?: string[];
  paths?: string[];
  roots?: string[];
  count?: number;
  allowed?: string[];
  [key: string]: unknown;
}

export interface ValidateUploadResult {
  ok: boolean;
  errors?: ValidationIssue[];
  warnings?: ValidationIssue[];
  row_flags?: { row?: number; photo?: string; flags?: string[] }[];
  dataset_root?: string;
  row_count?: number;
  image_count?: number;
}

export interface JobsResponse {
  ok: boolean;
  active: string | null;
  steps: Record<string, string>;
  jobs: Job[];
}

export interface RunSubmissionRequest {
  name: string;
  script_text: string;
  lang?: string;
  scope?: string;
  mode?: string;
  params?: string[];
  save_mode?: string;
  candidate_limit?: number | null;
}

export interface RunSubmissionResult {
  ok: boolean;
  name: string;
  version: number;
  scope?: string;
  mode?: string;
  n_cases?: number;
  metrics?: {
    n_eligible?: number;
    correct?: number;
    accuracy_pct?: number;
    accuracy_canonical_pct?: number;
    duration_ms?: number;
  };
  message?: string;
}

/** Optional shared secret when the backend has POI_API_TOKEN set. */
function apiToken(): string {
  try {
    return (import.meta.env.VITE_POI_API_TOKEN as string | undefined)?.trim() || "";
  } catch {
    return "";
  }
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  const token = apiToken();
  if (token) h["X-POI-Token"] = token;
  return h;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: authHeaders({ Accept: "application/json" }) });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function readError(res: Response, fallback: string): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as {
    detail?: string;
    message?: string;
    error?: string;
  };
  return data.detail || data.message || data.error || `${fallback} → HTTP ${res.status}`;
}

export interface ReconcileCandidate {
  rank: number;
  name: string;
  distance?: number | null;
  category?: string;
  lat?: number | null;
  lon?: number | null;
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
  /** Wide radius actually used by the probe (meters). */
  radius_m?: number;
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

/** Case photo URL. Galleries should pass ``thumb: true`` for a long-edge JPEG. */
export function photoUrl(
  dataset: string,
  photo: string,
  opts: { thumb?: boolean; w?: number } = {},
): string {
  const qs = new URLSearchParams({
    dataset,
    photo,
  });
  if (opts.thumb !== false) {
    // Default to thumbnails — full-res only when explicitly disabled.
    qs.set("thumb", "1");
    if (opts.w) qs.set("w", String(opts.w));
  }
  return `/api/poi-case-photo?${qs.toString()}`;
}

/** Format duration_ms as a short human string. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return `${m}m ${rem.toString().padStart(2, "0")}s`;
}

/** Relative time from ISO / local timestamp. */
export function relTime(iso: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 14) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Runtime dependency gate (requirements.txt, Swift/MapKit on macOS, …). */
export interface DepsStatusItem {
  key: string;
  label: string;
  ok: boolean;
  required: boolean;
  detail: string;
  fix?: string | null;
}

export interface DepsStatus {
  ok: boolean;
  ready: boolean;
  skipped?: boolean;
  platform?: string;
  message?: string;
  items?: DepsStatusItem[];
  missing?: { key: string; label: string; detail: string; fix?: string | null }[];
  warnings?: { key: string; label: string; detail: string; fix?: string | null }[];
  install_commands?: string[];
  requirements_file?: string;
}

/** Local-vs-remote git freshness (server runs fetch + rev-list). */
export interface GitSyncStatus {
  ok: boolean;
  status:
    | "current"
    | "ahead"
    | "behind"
    | "diverged"
    | "skipped"
    | "not_a_repo"
    | "check_failed";
  /** True when the UI must refuse to load until the user pulls. */
  update_required: boolean;
  message?: string;
  hint?: string | null;
  commands?: string[] | null;
  branch?: string;
  upstream?: string;
  local_sha?: string;
  local_short?: string;
  remote_sha?: string;
  remote_short?: string;
  behind?: number;
  ahead?: number;
}

export const api = {
  overview: () => getJSON<Overview>("/api/overview"),

  /** Hard runtime deps (pip + macOS Swift). Blocks SPA when not ready. */
  depsStatus: () => getJSON<DepsStatus>("/api/deps-status"),

  /** Compare local HEAD to upstream (fetch first). Blocks the SPA when behind. */
  gitStatus: (refresh = false) =>
    getJSON<GitSyncStatus>(
      refresh ? "/api/git-status?refresh=1" : "/api/git-status",
    ),

  runs: () => getJSON<{ runs: Run[] }>("/api/runs"),

  run: (name: string, version: number) =>
    getJSON<{ run: RunDetail }>(
      `/api/runs?name=${encodeURIComponent(name)}&version=${encodeURIComponent(version)}`,
    ),

  matchrate: (dataset = "all", mode = "exact") =>
    getJSON<MatchRate>(
      `/api/matchrate?dataset=${encodeURIComponent(dataset)}&mode=${encodeURIComponent(mode)}`,
    ),

  datasets: () => getJSON<DatasetsResponse>("/api/datasets"),

  jobs: () => getJSON<JobsResponse>("/api/jobs"),

  jobStatus: (jobId: string) =>
    getJSON<{ ok: boolean } & Job>(`/api/jobs/status?job_id=${encodeURIComponent(jobId)}`),

  case: (dataset: string, photo: string, runName?: string, version?: number) => {
    const qs = new URLSearchParams({ dataset, photo });
    if (runName) qs.set("run_name", runName);
    if (version != null) qs.set("version", String(version));
    return getJSON<CaseDetail>(`/api/case?${qs.toString()}`);
  },

  /**
   * Live MapKit nearby query for a coordinate (Investigate). Slow (~20–30s).
   * Optional ``radiusM`` overrides the wide radius (default 250; app path).
   */
  async mapkitProbe(lat: number, lon: number, radiusM?: number): Promise<ProbeResult> {
    const body: { lat: number; lon: number; radius_m?: number } = { lat, lon };
    if (radiusM != null && Number.isFinite(radiusM)) body.radius_m = radiusM;
    const res = await fetch("/api/mapkit/probe", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
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
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(c),
    });
    const data = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      done?: number;
      remaining?: number;
      message?: string;
    };
    if (!res.ok || data.ok === false)
      throw new Error(data.message || `/api/gt/reconcile → HTTP ${res.status}`);
    return { ok: true, done: data.done ?? 0, remaining: data.remaining ?? 0 };
  },

  /** Onboarding seed presets discovered on disk (disk-bundle path; UI uses upload). */
  async seedPresets(): Promise<SeedPresets> {
    return getJSON<SeedPresets>("/api/seed/presets");
  },

  /**
   * Onboarding: upload a seed-bundle ZIP (drag-and-drop). The ZIP mirrors
   * poi-data-seed/ — eval_set_reconciled.csv (required), dashboard_config.json,
   * generated/runs/*.json. Extraction is whitelisted + zip-slip safe server-side.
   */
  async seedUpload(file: File): Promise<{ ok: boolean; message?: string }> {
    const res = await fetch("/api/seed/upload", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/zip" }),
      body: file,
    });
    const data = (await res.json().catch(() => ({}))) as { ok?: boolean; message?: string };
    if (!res.ok) throw new Error(data.message || `/api/seed/upload → HTTP ${res.status}`);
    return { ok: data.ok ?? true, message: data.message };
  },

  /** Inject the bundled onboarding seed (initial dataset + baseline runs). */
  async seed(preset: string): Promise<{ ok: boolean; message?: string }> {
    const res = await fetch("/api/seed", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ preset }),
    });
    const data = (await res.json().catch(() => ({}))) as { ok?: boolean; message?: string };
    if (!res.ok) throw new Error(data.message || `/api/seed → HTTP ${res.status}`);
    return { ok: data.ok ?? true, message: data.message };
  },

  /** Submit a predict() script and score it. May take minutes for full cohorts. */
  async submitRun(req: RunSubmissionRequest): Promise<RunSubmissionResult> {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify(req),
    });
    const data = (await res.json().catch(() => ({}))) as RunSubmissionResult & {
      detail?: string;
      message?: string;
    };
    if (!res.ok || data.ok === false) {
      throw new Error(data.detail || data.message || `/api/run → HTTP ${res.status}`);
    }
    return data;
  },

  /** Start a background enrichment / maintenance job. */
  async startJob(
    step: string,
    params: {
      dataset?: string | null;
      only_empty?: boolean;
      delete_photos?: boolean;
      remove_config_source?: boolean;
    } = {},
  ): Promise<{ ok: boolean; job_id: string; step: string; status: string }> {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify({ step, ...params }),
    });
    if (!res.ok) throw new Error(await readError(res, "/api/jobs"));
    return (await res.json()) as { ok: boolean; job_id: string; step: string; status: string };
  },

  /** Ingest a dataset ZIP (starts a tracked job). */
  async ingest(file: File, dataset?: string): Promise<{ ok: boolean; job_id: string }> {
    const qs = dataset ? `?dataset=${encodeURIComponent(dataset)}` : "";
    const res = await fetch(`/api/ingest${qs}`, {
      method: "POST",
      headers: authHeaders({ Accept: "application/json" }),
      body: file,
    });
    if (!res.ok) throw new Error(await readError(res, "/api/ingest"));
    return (await res.json()) as { ok: boolean; job_id: string };
  },

  /** Validate an upload package without writing. */
  async validateUpload(file: File): Promise<ValidateUploadResult> {
    const res = await fetch("/api/validate-upload-package", {
      method: "POST",
      headers: authHeaders({ Accept: "application/json" }),
      body: file,
    });
    const data = (await res.json().catch(() => ({}))) as ValidateUploadResult & {
      message?: string;
    };
    if (!res.ok && data.ok === undefined) {
      throw new Error(data.message || `/api/validate-upload-package → HTTP ${res.status}`);
    }
    return {
      ok: !!data.ok,
      errors: data.errors,
      warnings: data.warnings,
      row_flags: data.row_flags,
      dataset_root: data.dataset_root,
      row_count: data.row_count,
      image_count: data.image_count,
    };
  },

  /** Download the sample upload-package ZIP (manifest + placeholder photos). */
  async downloadTemplate(filename = "poi-dataset-template.zip"): Promise<void> {
    const res = await fetch("/api/dataset-template", {
      headers: authHeaders({ Accept: "application/zip" }),
    });
    if (!res.ok) throw new Error(await readError(res, "/api/dataset-template"));
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  },
};

/** Escape a CSV field (RFC-style quotes). */
export function csvEscape(value: string | number | boolean | null | undefined): string {
  const s = value == null ? "" : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

/** Build a CSV string from header + row objects. */
export function toCsv(
  headers: string[],
  rows: Record<string, string | number | boolean | null | undefined>[],
): string {
  const lines = [headers.map(csvEscape).join(",")];
  for (const row of rows) {
    lines.push(headers.map((h) => csvEscape(row[h])).join(","));
  }
  return lines.join("\n") + "\n";
}

/** Trigger a browser download of text content. */
export function downloadText(filename: string, text: string, mime = "text/csv;charset=utf-8"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** True when the backend has no dataset loaded yet (first-run / onboarding). */
export function isEmpty(o: Overview): boolean {
  return !o.csv_present || o.data_state === "empty" || (o.sources?.length ?? 0) === 0;
}

/** Pick the highest-accuracy scored run. */
export function bestRun(runs: Run[]): Run | null {
  const scored = runs.filter((r) => typeof r.accuracy_pct === "number");
  return scored.reduce<Run | null>(
    (b, r) => (b === null || (r.accuracy_pct ?? 0) > (b.accuracy_pct ?? 0) ? r : b),
    null,
  );
}
