import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import MapPicker, { type MapCandidate } from "../components/MapPicker";
import CandidateRow, { type CandidateRowData } from "../components/CandidateRow";
import { api, photoUrl, type CaseCandidate, type CaseDetail } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./CaseInspector.module.css";

/** App MapKit nearby path: strict 80 m → wide 250 m (ls_mapkit_probe / PlaceSearchViewModel). */
const MAPKIT_STRICT_RADIUS_M = 80;
const MAPKIT_WIDE_RADIUS_M = 250;
/** Show expand-search UI only when the stored app-radius list is this sparse. */
const SPARSE_CANDIDATE_THRESHOLD = 5;
/** Investigate-only wider radii (not the scored app path). */
const EXPAND_RADIUS_PRESETS_M = [500, 1000, 2000] as const;

type ProbeCand = {
  rank: number;
  name: string;
  distance?: number | null;
  category?: string;
  lat?: number | null;
  lon?: number | null;
};

function normName(s: string) {
  return (s || "").trim().toLowerCase();
}

function toRowData(
  cands: CaseCandidate[] | ProbeCand[],
  opts: {
    gtNames: Set<string>;
    prediction: string;
    correct: boolean;
    runLimit: number | null;
    /** Mark names that were already in the app-radius list */
    baselineNames?: Set<string>;
    /** Tag rows beyond the app wide radius */
    appWideM?: number;
  },
): CandidateRowData[] {
  const total = cands.length;
  return cands.map((cand, i) => {
    const isGt = opts.gtNames.has(normName(cand.name));
    const isPick = normName(cand.name) === normName(opts.prediction);
    const stateKey = isPick ? (opts.correct ? "hit" : "miss") : isGt ? "gt" : "default";
    let tag = isPick
      ? opts.correct
        ? "✓ PICK = GT"
        : "✗ PICK ≠ GT"
      : isGt
        ? "GT"
        : undefined;
    const beyondRun =
      "in_run_window" in cand &&
      (cand.in_run_window === false ||
        (opts.runLimit != null && cand.rank > opts.runLimit));
    const beyondApp =
      opts.appWideM != null &&
      cand.distance != null &&
      Number.isFinite(cand.distance) &&
      cand.distance > opts.appWideM;
    const isNew =
      opts.baselineNames != null &&
      !opts.baselineNames.has(normName(cand.name));
    if (!tag && isNew && beyondApp) tag = "NEW · >250m";
    else if (!tag && isNew) tag = "NEW";
    else if (!tag && beyondApp) tag = `>${opts.appWideM}m`;
    return {
      rank: cand.rank,
      name: cand.name || "—",
      score: cand.distance != null ? `${Math.round(cand.distance)}m` : "·",
      scoreValue: total > 0 ? (total - i) / total : 0,
      distance: beyondRun ? "out of run K" : "",
      state: stateKey as CandidateRowData["state"],
      tag,
    };
  });
}

function toMapCands(
  cands: { lat?: number | null; lon?: number | null; rank?: number; name?: string }[],
  gtNames: Set<string>,
  prediction: string,
  correct: boolean,
): MapCandidate[] {
  return cands
    .filter(
      (cand) =>
        cand.lat != null &&
        cand.lon != null &&
        Number.isFinite(Number(cand.lat)) &&
        Number.isFinite(Number(cand.lon)),
    )
    .map((cand) => {
      const isGt = gtNames.has(normName(cand.name || ""));
      const isPick = normName(cand.name || "") === normName(prediction);
      const kind: MapCandidate["kind"] = isPick
        ? correct
          ? "hit"
          : "pick"
        : isGt
          ? "gt"
          : "default";
      return {
        lat: Number(cand.lat),
        lon: Number(cand.lon),
        rank: cand.rank,
        name: cand.name,
        kind,
      };
    });
}

export default function CaseInspector() {
  const [params] = useSearchParams();
  const dataset = params.get("dataset") || "";
  const photo = params.get("photo") || "";
  const runName = params.get("run_name") || params.get("name") || "";
  const versionRaw = params.get("version");
  const version = versionRaw ? Number(versionRaw) : undefined;

  const state = useAsync<CaseDetail | null>(
    () =>
      dataset && photo
        ? api.case(dataset, photo, runName || undefined, version)
        : Promise.resolve(null),
    [dataset, photo, runName, version],
  );

  // Sparse-list expand search (session-only; never written to eval).
  const [expandRadius, setExpandRadius] = useState<number>(EXPAND_RADIUS_PRESETS_M[0]);
  const [probing, setProbing] = useState(false);
  const [probeMsg, setProbeMsg] = useState<string | null>(null);
  const [probeCands, setProbeCands] = useState<ProbeCand[] | null>(null);
  const [probeRadius, setProbeRadius] = useState<number | null>(null);

  // Drop expand results when navigating to another case.
  useEffect(() => {
    setProbeCands(null);
    setProbeRadius(null);
    setProbeMsg(null);
    setProbing(false);
  }, [dataset, photo, runName, version]);

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
    return (
      <main className={styles.main}>
        Couldn’t load case — {state.status === "error" ? state.error.message : "not found"}
      </main>
    );

  const c = state.data;
  const candTotal = c.candidate_total ?? c.candidates.length;
  const runLimit = c.candidate_limit ?? null;
  const sparse = candTotal <= SPARSE_CANDIDATE_THRESHOLD;
  const hasCoord =
    Number.isFinite(parseFloat(c.lat)) && Number.isFinite(parseFloat(c.lon));
  const photoLat = parseFloat(c.lat);
  const photoLon = parseFloat(c.lon);

  const gtNames = new Set([c.gt_mapkit, c.gt].map(normName).filter(Boolean));
  const baselineNames = new Set(
    c.candidates.map((x) => normName(x.name)).filter(Boolean),
  );

  const signals = [
    { name: "exif.gps", value: c.signals.gps, present: !!c.signals.gps },
    {
      name: "ocr.text",
      value: c.signals.ocr ? `“${c.signals.ocr}”` : "— none",
      present: !!c.signals.ocr,
    },
    {
      name: "mapkit.nearby",
      value: candTotal
        ? `${candTotal} candidates${runLimit != null ? ` · run top-${runLimit}` : ""}`
        : c.signals.nearby
          ? `${c.signals.nearby} candidates`
          : "— none",
      present: candTotal > 0 || !!c.signals.nearby,
    },
    {
      name: "category",
      value: c.signals.category || "— none",
      present: !!c.signals.category,
    },
  ];

  const shown = c.candidates.length;
  const baseRows = toRowData(c.candidates, {
    gtNames,
    prediction: c.prediction,
    correct: c.correct,
    runLimit,
  });

  const displayCands: CaseCandidate[] | ProbeCand[] = probeCands ?? c.candidates;
  const displayRows =
    probeCands != null
      ? toRowData(probeCands, {
          gtNames,
          prediction: c.prediction,
          correct: c.correct,
          runLimit: null,
          baselineNames,
          appWideM: MAPKIT_WIDE_RADIUS_M,
        })
      : baseRows;

  const mapCands = toMapCands(displayCands, gtNames, c.prediction, c.correct);
  const mapOuterR = probeRadius ?? MAPKIT_WIDE_RADIUS_M;
  const mapInnerR =
    probeRadius != null ? MAPKIT_WIDE_RADIUS_M : MAPKIT_STRICT_RADIUS_M;
  const radiusLabel =
    probeRadius != null
      ? `Expanded probe · ${probeRadius}m · ${probeCands?.length ?? 0} hits · app path was ${MAPKIT_WIDE_RADIUS_M}m (${candTotal} cands)`
      : `MapKit nearby · strict ${MAPKIT_STRICT_RADIUS_M}m · wide ${MAPKIT_WIDE_RADIUS_M}m · ${candTotal || shown} in wide`;

  async function runExpandProbe() {
    if (!hasCoord || probing) return;
    setProbing(true);
    setProbeMsg(null);
    try {
      const res = await api.mapkitProbe(photoLat, photoLon, expandRadius);
      if (!res.ok) {
        setProbeMsg(res.message || "MapKit probe failed.");
        return;
      }
      const list: ProbeCand[] = (res.candidates || []).map((x, i) => ({
        rank: x.rank ?? i + 1,
        name: x.name || "",
        distance: x.distance,
        category: x.category,
        lat: x.lat,
        lon: x.lon,
      }));
      setProbeCands(list);
      setProbeRadius(res.radius_m ?? expandRadius);
      if (list.length === 0) {
        setProbeMsg(`No named POIs within ${res.radius_m ?? expandRadius}m.`);
      } else {
        const novel = list.filter((x) => !baselineNames.has(normName(x.name))).length;
        setProbeMsg(
          `Found ${list.length} within ${res.radius_m ?? expandRadius}m` +
            (novel ? ` · ${novel} new vs app ${MAPKIT_WIDE_RADIUS_M}m list` : " · same names as app list"),
        );
      }
    } catch (e) {
      setProbeMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setProbing(false);
    }
  }

  function clearExpand() {
    setProbeCands(null);
    setProbeRadius(null);
    setProbeMsg(null);
  }

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
              <span
                className={styles.missPill}
                style={{ background: "var(--success-bg)", color: "var(--success-fg)" }}
              >
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
        {/* photo column — stacked photo, signals, map */}
        <div className={styles.photoCol}>
          <div className={styles.photo}>
            <img
              className={styles.photoImg}
              src={photoUrl(c.dataset, c.photo, { thumb: true, w: 900 })}
              alt={c.photo}
              loading="lazy"
            />
          </div>
          <div className={styles.signals}>
            <p className={styles.miniLabel}>Signals on this case</p>
            {signals.map((s) => (
              <div key={s.name} className={styles.signalRow}>
                <span
                  className={styles.signalDot}
                  style={{
                    background: s.present ? "var(--success-fg)" : "var(--text-tertiary)",
                  }}
                />
                <span className={styles.signalName}>{s.name}</span>
                <span className={s.present ? styles.signalValue : styles.signalMuted}>
                  {s.value}
                </span>
              </div>
            ))}
          </div>
          {hasCoord && (
            <div className={styles.mapWrap}>
              <div className={styles.mapBox}>
                <MapPicker
                  photo={{ lat: photoLat, lon: photoLon }}
                  point={{ lat: photoLat, lon: photoLon }}
                  candidates={mapCands}
                  radiusM={mapOuterR}
                  radiusInnerM={mapInnerR}
                />
              </div>
              <p className={styles.mapCaption}>{radiusLabel}</p>
              <div className={styles.mapLegend}>
                <span className={styles.legendItem}>
                  <span
                    className={styles.legendDot}
                    style={{ background: "var(--warning-fg)" }}
                  />
                  photo
                </span>
                <span className={styles.legendItem}>
                  <span
                    className={styles.legendRing}
                    style={{
                      borderColor: "var(--accent-default)",
                      borderStyle: probeRadius != null ? "solid" : "dashed",
                    }}
                  />
                  {probeRadius != null ? `${MAPKIT_WIDE_RADIUS_M}m app` : `${MAPKIT_STRICT_RADIUS_M}m`}
                </span>
                <span className={styles.legendItem}>
                  <span
                    className={styles.legendRing}
                    style={{ borderColor: "var(--accent-default)" }}
                  />
                  {probeRadius != null ? `${probeRadius}m probe` : `${MAPKIT_WIDE_RADIUS_M}m`}
                </span>
                {mapCands.length > 0 && (
                  <>
                    <span className={styles.legendItem}>
                      <span
                        className={styles.legendDot}
                        style={{ background: "var(--text-tertiary)" }}
                      />
                      cand
                    </span>
                    <span className={styles.legendItem}>
                      <span
                        className={styles.legendDot}
                        style={{ background: "var(--success-fg)" }}
                      />
                      GT
                    </span>
                    <span className={styles.legendItem}>
                      <span
                        className={styles.legendDot}
                        style={{ background: "var(--danger-fg)" }}
                      />
                      pick
                    </span>
                  </>
                )}
              </div>
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

          {/* Sparse list → optional wider re-search (investigate only) */}
          {sparse && hasCoord && (
            <div className={styles.expandCard}>
              <p className={styles.miniLabel}>Sparse list — widen MapKit search</p>
              <p className={styles.expandBody}>
                Only {candTotal} candidate{candTotal === 1 ? "" : "s"} inside the app{" "}
                {MAPKIT_WIDE_RADIUS_M}m radius. Re-query a larger circle to see if GT
                (or better options) appear farther out. Explore-only — not written to
                the eval set.
              </p>
              <div className={styles.expandControls}>
                <div className={styles.radiusChips}>
                  {EXPAND_RADIUS_PRESETS_M.map((r) => (
                    <button
                      key={r}
                      type="button"
                      className={`${styles.radiusChip} ${
                        expandRadius === r ? styles.radiusChipOn : ""
                      }`}
                      disabled={probing}
                      onClick={() => setExpandRadius(r)}
                    >
                      {r}m
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className={styles.expandBtn}
                  disabled={probing}
                  onClick={() => void runExpandProbe()}
                >
                  {probing
                    ? "Querying MapKit… (~20–30s)"
                    : `Re-search at ${expandRadius}m`}
                </button>
                {probeCands != null && (
                  <button
                    type="button"
                    className={styles.expandReset}
                    disabled={probing}
                    onClick={clearExpand}
                  >
                    Back to app list
                  </button>
                )}
              </div>
              {probeMsg && <p className={styles.expandMsg}>{probeMsg}</p>}
            </div>
          )}

          <div className={styles.card}>
            <p className={styles.miniLabel}>
              {probeCands != null
                ? `Expanded candidates · ${probeRadius}m · ${displayRows.length}`
                : `Candidates — mapkit.nearby · ${shown}${
                    candTotal > shown ? ` of ${candTotal}` : ""
                  }${runLimit != null ? ` · run top-${runLimit}` : ""}`}
            </p>
            {displayRows.length === 0 && (
              <p className={styles.verdictBody}>
                {probeCands != null
                  ? "No MapKit candidates in the expanded radius."
                  : "No MapKit candidates recorded for this photo."}
              </p>
            )}
            {displayRows.map((r) => (
              <CandidateRow key={`${r.name}-${r.rank}-${r.tag || ""}`} {...r} />
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
