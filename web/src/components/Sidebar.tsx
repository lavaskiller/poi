import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { api, type SeedPresets } from "../lib/api";
import { notifyDataChanged, useRefreshOnFocus } from "../lib/dataRefresh";
import { useAsync } from "../lib/useAsync";
import styles from "./Sidebar.module.css";

const WORKFLOW = [
  { to: "/", label: "Home", end: true },
  { to: "/new-run", label: "New run" },
  { to: "/results", label: "Results" },
  { to: "/compare", label: "Compare" },
  { to: "/retrieval", label: "Retrieval" },
];

const DATA = [
  { to: "/datasets", label: "Datasets" },
  { to: "/reconcile", label: "Reconcile GT" },
  { to: "/jobs", label: "Jobs" },
];

function NavItem({ to, label, end }: { to: string; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => [styles.navItem, isActive ? styles.active : ""].join(" ")}
    >
      <span className={styles.icon} aria-hidden />
      <span className={styles.navLabel}>{label}</span>
    </NavLink>
  );
}

export default function Sidebar() {
  const overview = useAsync(() => api.overview(), []);
  // Long-lived chrome: refresh dataset count after reconcile / ingest / delete.
  useRefreshOnFocus(overview.softReload);
  const n =
    overview.status === "ready"
      ? overview.data.sources?.length ?? overview.data.datasets?.length ?? 0
      : null;

  const [seedOpen, setSeedOpen] = useState(false);
  const [presets, setPresets] = useState<SeedPresets | null>(null);
  const [presetId, setPresetId] = useState("default");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmForce, setConfirmForce] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!seedOpen) return;
    let cancelled = false;
    api
      .seedPresets()
      .then((p) => {
        if (cancelled) return;
        setPresets(p);
        const first = p.presets.find((x) => x.available) ?? p.presets[0];
        if (first) setPresetId(first.id);
      })
      .catch(() => {
        if (!cancelled) setPresets({ bundle_present: false, seed_path: "poi-data-seed", presets: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [seedOpen]);

  const available = presets?.presets.filter((p) => p.available) ?? [];
  const hasLocal = presets?.bundle_present === true && available.length > 0;
  const alreadyHasData = overview.status === "ready" && (overview.data.total ?? 0) > 0;

  const afterSeed = (message?: string) => {
    setMsg(message || "Seed applied.");
    setErr(null);
    setConfirmForce(false);
    notifyDataChanged("seed");
    overview.softReload();
    // Full reload so boot gates / Home readiness pick up new CSV + relations.
    window.setTimeout(() => {
      window.location.assign("/");
    }, 600);
  };

  const reseedLocal = async () => {
    if (alreadyHasData && !confirmForce) {
      setErr("Live data exists — tick “Replace live data” to re-apply the seed.");
      return;
    }
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const res = await api.seed(presetId, { force: alreadyHasData || confirmForce });
      if (res.already_seeded && !confirmForce) {
        setMsg(res.message || "Already seeded.");
        return;
      }
      afterSeed(res.message);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const reseedUpload = async (file: File | null | undefined) => {
    if (!file) return;
    if (!/\.zip$/i.test(file.name)) {
      setErr("Need a seed-bundle .zip (not a dataset import template).");
      return;
    }
    if (alreadyHasData && !confirmForce) {
      setErr("Live data exists — tick “Replace live data” before uploading a seed ZIP.");
      return;
    }
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const res = await api.seedUpload(file, { force: alreadyHasData || confirmForce });
      if (res.already_seeded && !confirmForce) {
        setMsg(res.message || "Already seeded.");
        return;
      }
      afterSeed(res.message);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandMark} aria-hidden />
        <span className={styles.brandName}>POI Eval</span>
        <span className={styles.brandTag}>internal</span>
      </div>

      <nav className={styles.group}>
        <p className={`sectionLabel ${styles.groupLabel}`}>Workflow</p>
        {WORKFLOW.map((i) => (
          <NavItem key={i.to} {...i} />
        ))}
      </nav>

      <nav className={styles.group}>
        <p className={`sectionLabel ${styles.groupLabel}`}>Data</p>
        {DATA.map((i) => (
          <NavItem key={i.to} {...i} />
        ))}
      </nav>

      <div className={styles.spacer} />

      <div className={styles.seedPanel}>
        <button
          type="button"
          className={styles.seedToggle}
          aria-expanded={seedOpen}
          onClick={() => {
            setSeedOpen((o) => !o);
            setErr(null);
            setMsg(null);
          }}
        >
          <span className={styles.seedToggleTitle}>Re-apply seed</span>
          <span className={styles.seedToggleHint}>{seedOpen ? "▾" : "▸"}</span>
        </button>
        {seedOpen && (
          <div className={styles.seedBody}>
            <p className={styles.seedDesc}>
              Restore demo CSV, label relations, baselines, MapKit candidates, and photos from the
              seed bundle. Use this if relations/runs are missing or data is out of date.
            </p>
            {alreadyHasData && (
              <label className={styles.seedConfirm}>
                <input
                  type="checkbox"
                  checked={confirmForce}
                  onChange={(e) => setConfirmForce(e.target.checked)}
                  disabled={busy}
                />
                <span>
                  Replace live data (overwrites eval CSV, relations, seed photos, generated runs)
                </span>
              </label>
            )}
            {hasLocal ? (
              <>
                {available.length > 1 && (
                  <label className={styles.seedLabel}>
                    Preset
                    <select
                      className={styles.seedSelect}
                      value={presetId}
                      disabled={busy}
                      onChange={(e) => setPresetId(e.target.value)}
                    >
                      {available.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.label || p.id}
                          {p.rows != null ? ` · ${p.rows} rows` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button
                  type="button"
                  className={styles.seedBtn}
                  disabled={busy || (alreadyHasData && !confirmForce)}
                  onClick={() => void reseedLocal()}
                >
                  {busy ? "Applying…" : "Load local seed"}
                </button>
                <p className={styles.seedPath}>
                  Disk: <code>{presets?.seed_path || "poi-data-seed"}/</code>
                </p>
              </>
            ) : (
              <p className={styles.seedPath}>
                No <code>poi-data-seed/</code> on disk — upload a seed ZIP below.
              </p>
            )}
            <div className={styles.seedOr}>or upload seed ZIP</div>
            <button
              type="button"
              className={styles.seedBtnSecondary}
              disabled={busy || (alreadyHasData && !confirmForce)}
              onClick={() => fileRef.current?.click()}
            >
              {busy ? "Uploading…" : "Choose seed ZIP…"}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".zip,application/zip"
              hidden
              onChange={(e) => void reseedUpload(e.target.files?.[0])}
            />
            {msg && <p className={styles.seedMsg}>{msg}</p>}
            {err && <p className={styles.seedErr}>{err}</p>}
          </div>
        )}
      </div>

      <div className={styles.status}>
        <span className={styles.statusDot} aria-hidden />
        <span className={styles.statusText}>
          {overview.status === "error"
            ? "API unreachable"
            : n == null
              ? "API connected…"
              : `API connected · ${n} dataset${n === 1 ? "" : "s"}`}
        </span>
      </div>
    </aside>
  );
}
