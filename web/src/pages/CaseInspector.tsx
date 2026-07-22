import { Link, useSearchParams } from "react-router-dom";
import MapPicker from "../components/MapPicker";
import CandidateRow, { type CandidateRowData } from "../components/CandidateRow";
import { api, type CaseDetail } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./CaseInspector.module.css";

export default function CaseInspector() {
  const [params] = useSearchParams();
  const dataset = params.get("dataset") || "";
  const photo = params.get("photo") || "";

  const state = useAsync<CaseDetail | null>(
    () => (dataset && photo ? api.case(dataset, photo) : Promise.resolve(null)),
    [dataset, photo],
  );

  if (!dataset || !photo) {
    return (
      <main className={styles.main}>
        <p className={styles.sub}>Open a case from the Run results gallery to inspect it.</p>
        <Link className={styles.navBtn} to="/results">
          ← Back to results
        </Link>
      </main>
    );
  }
  if (state.status === "loading") return <main className={styles.main}>Loading case…</main>;
  if (state.status === "error" || !state.data)
    return <main className={styles.main}>Couldn’t load case — {state.status === "error" ? state.error.message : "not found"}</main>;

  const c = state.data;
  const signals = [
    { name: "exif.gps", value: c.signals.gps, present: !!c.signals.gps },
    { name: "ocr.text", value: c.signals.ocr ? `“${c.signals.ocr}”` : "— none", present: !!c.signals.ocr },
    { name: "mapkit.nearby", value: c.signals.nearby ? `${c.signals.nearby} candidates` : "— none", present: !!c.signals.nearby },
    { name: "category", value: c.signals.category || "— none", present: !!c.signals.category },
  ];

  const norm = (s: string) => (s || "").trim().toLowerCase();
  const total = c.candidates.length;
  const rows: CandidateRowData[] = c.candidates.map((cand, i) => {
    const isGt = norm(cand.name) === norm(c.gt);
    const isPick = norm(cand.name) === norm(c.prediction);
    const stateKey = isPick ? (c.correct ? "hit" : "miss") : isGt ? "gt" : "default";
    const tag = isPick ? (c.correct ? "✓ PICK = GT" : "✗ PICK ≠ GT") : isGt ? "GT" : undefined;
    return {
      rank: cand.rank,
      name: cand.name || "—",
      score: cand.distance != null ? `${Math.round(cand.distance)}m` : "·",
      scoreValue: total > 0 ? (total - i) / total : 0,
      distance: "",
      state: stateKey,
      tag,
    };
  });

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>
            Case inspector{c.run ? ` · ${c.run.name} v${c.run.version}` : ""}
          </p>
          <div className={styles.titleRow}>
            <h1 className={styles.h1}>
              {c.dataset} — {c.gt || c.photo}
            </h1>
            {!c.correct ? (
              <span className={styles.missPill}>{c.match_kind || "MISS"}</span>
            ) : (
              <span className={styles.missPill} style={{ background: "var(--success-bg)", color: "var(--success-fg)" }}>
                CORRECT
              </span>
            )}
          </div>
          <p className={styles.sub}>
            dataset {c.dataset} · gt_mapkit {c.gt_mapkit || "—"} · photo {c.photo}
          </p>
        </div>
        <Link className={styles.navBtn} to="/results">
          ← Results
        </Link>
      </header>

      <div className={styles.split}>
        {/* photo column */}
        <div className={styles.photoCol}>
          <div className={styles.photo}>
            <img className={styles.photoImg} src={c.image} alt={c.photo} loading="lazy" />
          </div>
          <div className={styles.signals}>
            <p className={styles.miniLabel}>Signals on this case</p>
            {signals.map((s) => (
              <div key={s.name} className={styles.signalRow}>
                <span
                  className={styles.signalDot}
                  style={{ background: s.present ? "var(--success-fg)" : "var(--text-tertiary)" }}
                />
                <span className={styles.signalName}>{s.name}</span>
                <span className={s.present ? styles.signalValue : styles.signalMuted}>{s.value}</span>
              </div>
            ))}
          </div>
          {Number.isFinite(parseFloat(c.lat)) && Number.isFinite(parseFloat(c.lon)) && (
            <div className={styles.mapBox}>
              <MapPicker
                photo={{ lat: parseFloat(c.lat), lon: parseFloat(c.lon) }}
                point={{ lat: parseFloat(c.lat), lon: parseFloat(c.lon) }}
              />
            </div>
          )}
        </div>

        {/* detail column */}
        <div className={styles.detailCol}>
          <div
            className={styles.verdict}
            style={c.correct ? { background: "var(--success-bg)" } : undefined}
          >
            <p
              className={styles.verdictTitle}
              style={c.correct ? { color: "var(--success-fg)" } : undefined}
            >
              {c.correct ? "Correct — prediction matched ground truth" : "Wrong pick"}
            </p>
            <p className={styles.verdictBody}>
              {c.correct
                ? `Matched as ${c.match_kind || "exact"}.`
                : `Predicted “${c.prediction || "— nothing"}” · match kind ${c.match_kind || "—"}.`}
            </p>
          </div>

          <div className={styles.card}>
            <div className={styles.pvgRow}>
              <span className={styles.pvgLabel}>PREDICTED</span>
              <span
                className={`${styles.pvgName} ${c.correct ? styles.success : styles.danger}`}
              >
                {c.prediction || "— no candidate"}
              </span>
            </div>
            <div className={styles.pvgRow}>
              <span className={styles.pvgLabel}>GROUND TRUTH</span>
              <span className={`${styles.pvgName} ${styles.success}`}>{c.gt || "—"}</span>
              <span className={styles.gtSrc}>src · mapkit ({c.gt_mapkit || "—"})</span>
            </div>
          </div>

          <div className={styles.card}>
            <p className={styles.miniLabel}>Candidates — mapkit.nearby · {total}</p>
            {rows.length === 0 && (
              <p className={styles.verdictBody}>No MapKit candidates recorded for this photo.</p>
            )}
            {rows.map((r) => (
              <CandidateRow key={`${r.name}-${r.rank}`} {...r} />
            ))}
          </div>

          {c.reason && (
            <div className={styles.why}>
              <p className={styles.miniLabel}>Why — predict() reason</p>
              <p className={styles.whyText}>{c.reason}</p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
