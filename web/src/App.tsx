import { useState } from "react";
import { Routes, Route, Outlet } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Home from "./pages/Home";
import NewRun from "./pages/NewRun";
import Results from "./pages/Results";
import CaseInspector from "./pages/CaseInspector";
import Compare from "./pages/Compare";
import Datasets from "./pages/Datasets";
import RetrievalDiagnostics from "./pages/RetrievalDiagnostics";
import ReconcileMapKit from "./pages/ReconcileMapKit";
import Onboarding from "./pages/Onboarding";
import Jobs from "./pages/Jobs";
import {
  api,
  isEmpty,
  type DepsStatus,
  type GitSyncStatus,
  type Overview,
} from "./lib/api";
import { useAsync } from "./lib/useAsync";
import styles from "./App.module.css";

function Layout() {
  return (
    <div style={{ display: "flex", alignItems: "stretch", height: "100%" }}>
      <Sidebar />
      <Outlet />
    </div>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="new-run" element={<NewRun />} />
        <Route path="results" element={<Results />} />
        <Route path="case" element={<CaseInspector />} />
        <Route path="compare" element={<Compare />} />
        <Route path="datasets" element={<Datasets />} />
        <Route path="reconcile" element={<ReconcileMapKit />} />
        <Route path="retrieval" element={<RetrievalDiagnostics />} />
        <Route path="jobs" element={<Jobs />} />
      </Route>
    </Routes>
  );
}

type BootState =
  | { kind: "deps_missing"; deps: DepsStatus }
  | { kind: "update_required"; git: GitSyncStatus }
  | {
      kind: "ready";
      git: GitSyncStatus;
      overview: Overview;
      deps: DepsStatus;
      backendSkew?: boolean;
    };

function isHttpStatus(err: unknown, code: number): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return new RegExp(`\\bHTTP ${code}\\b`).test(msg);
}

/**
 * Load deps gate. If the backend is older than this UI (404 on /api/deps-status),
 * soft-skip so a version skew does not hard-lock the app forever.
 */
async function resolveDeps(): Promise<{ deps: DepsStatus; skew: boolean }> {
  try {
    const deps = await api.depsStatus();
    return { deps, skew: false };
  } catch (e) {
    if (isHttpStatus(e, 404)) {
      return {
        skew: true,
        deps: {
          ok: true,
          ready: true,
          skipped: true,
          message:
            "Backend is missing /api/deps-status (old server.py or a different clone). Continuing without the deps gate.",
          install_commands: [
            "# UI and server must be the SAME git clone, then:",
            "git pull --ff-only",
            "python3 -m pip install -r requirements.txt",
            "# stop whatever is on :8420, then from THIS repo:",
            "python3 server.py",
          ],
        },
      };
    }
    throw e;
  }
}

function DepsMissingScreen({
  deps,
  onRetry,
}: {
  deps: DepsStatus;
  onRetry: () => void;
}) {
  const cmds =
    deps.install_commands?.length
      ? deps.install_commands
      : ["python3 -m pip install -r requirements.txt"];
  const missing = deps.missing ?? [];
  return (
    <div className={styles.center}>
      <span className={styles.errorTitle}>Dependencies missing</span>
      <span className={styles.centerText}>
        {deps.message ||
          "Required runtime dependencies are not installed. Fix them before using the eval UI."}
      </span>
      {missing.length > 0 && (
        <ul className={styles.centerList}>
          {missing.map((m) => (
            <li key={m.key}>
              <strong>{m.label}</strong>
              {m.detail ? ` — ${m.detail}` : ""}
            </li>
          ))}
        </ul>
      )}
      <pre className={styles.centerCode}>{cmds.join("\n")}</pre>
      <span className={styles.centerText}>
        MapKit is not a pip package — on macOS it needs system <code>swift</code>{" "}
        (Xcode / CLT). Restart <code>python3 server.py</code> from the same repo
        as this UI after installing.
      </span>
      <button type="button" className={styles.retry} onClick={onRetry}>
        Re-check
      </button>
    </div>
  );
}

async function waitForBackend(timeoutMs = 45000): Promise<boolean> {
  const start = Date.now();
  // Give the re-exec a moment to die before the first probe.
  await new Promise((r) => setTimeout(r, 600));
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch("/api/health", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (res.ok) return true;
    } catch {
      // server still restarting
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function UpdateRequiredScreen({
  git,
  onRetry,
}: {
  git: GitSyncStatus;
  onRetry: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"idle" | "pulling" | "restarting">("idle");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionDetail, setActionDetail] = useState<string | null>(null);

  const cmds = git.commands?.length
    ? git.commands
    : ["git pull --ff-only", "# then restart: python3 server.py"];

  const supportsPull =
    Array.isArray(git.features) && git.features.includes("git-pull");

  async function finishAfterRestart(detail: string) {
    setActionDetail(detail);
    setPhase("restarting");
    const up = await waitForBackend();
    if (!up) {
      setActionError(
        "Code may have been pulled, but the server did not come back. Restart `python3 server.py` in the terminal, then Re-check.",
      );
      setPhase("idle");
      setBusy(false);
      return;
    }
    onRetry();
  }

  async function handleUpdate() {
    setBusy(true);
    setActionError(null);
    setActionDetail(null);
    setPhase("pulling");
    try {
      const result = await api.gitPull({ restart: true });
      if (result.restarting || result.restart_required) {
        await finishAfterRestart(result.message || "Pull succeeded.");
        return;
      }
      setActionDetail(result.message || "Already up to date.");
      onRetry();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // Old backend without /api/git-pull → fall back to manual instructions.
      if (/\bHTTP 404\b/.test(msg) || /not found/i.test(msg)) {
        setActionError(
          "This backend does not support one-click Update yet. Run the commands below, restart the server, then Re-check.",
        );
        setPhase("idle");
        setBusy(false);
        return;
      }
      // Connection dropped while the server re-exec'd after a successful pull.
      if (
        /Failed to fetch|NetworkError|Load failed|fetch/i.test(msg) ||
        msg === "Failed to fetch"
      ) {
        await finishAfterRestart("Connection dropped during restart — waiting for server…");
        return;
      }
      setActionError(msg);
      setPhase("idle");
      setBusy(false);
    }
  }

  return (
    <div className={styles.center}>
      <span className={styles.errorTitle}>Update required</span>
      <span className={styles.centerText}>
        {git.message ||
          "This checkout is behind the remote. Pull the latest code before using the eval UI."}
      </span>
      {(git.local_short || git.remote_short || git.upstream) && (
        <span className={styles.centerMeta}>
          {git.branch ? `${git.branch}` : "HEAD"}
          {git.local_short ? ` @ ${git.local_short}` : ""}
          {git.upstream ? ` · upstream ${git.upstream}` : ""}
          {git.remote_short ? ` @ ${git.remote_short}` : ""}
          {typeof git.behind === "number" && git.behind > 0
            ? ` · ${git.behind} behind`
            : ""}
        </span>
      )}
      {phase === "restarting" && (
        <>
          <span className={styles.spinner} aria-hidden />
          <span className={styles.centerText}>
            {actionDetail || "Restarting server to load the new code…"}
          </span>
        </>
      )}
      {phase === "pulling" && (
        <>
          <span className={styles.spinner} aria-hidden />
          <span className={styles.centerText}>Pulling latest commits…</span>
        </>
      )}
      {actionError && (
        <span className={styles.actionError} role="alert">
          {actionError}
        </span>
      )}
      {actionDetail && phase === "idle" && !actionError && (
        <span className={styles.centerText}>{actionDetail}</span>
      )}
      <div className={styles.actionRow}>
        <button
          type="button"
          className={styles.primary}
          onClick={handleUpdate}
          disabled={busy}
          title={
            supportsPull
              ? "Run git pull --ff-only on the server, then restart"
              : "One-click pull (falls back to manual commands if unsupported)"
          }
        >
          {busy
            ? phase === "restarting"
              ? "Restarting…"
              : "Updating…"
            : "Update"}
        </button>
        <button
          type="button"
          className={styles.retry}
          onClick={onRetry}
          disabled={busy}
        >
          Re-check
        </button>
      </div>
      <span className={styles.centerText}>
        Or run these commands yourself if automatic update fails (dirty tree,
        diverged branch, or offline):
      </span>
      <pre className={styles.centerCode}>{cmds.join("\n")}</pre>
      {git.hint && phase === "idle" && (
        <span className={styles.centerText}>{git.hint}</span>
      )}
    </div>
  );
}

export default function App() {
  // Boot: deps (soft-skip if endpoint 404) → git freshness → overview.
  const boot = useAsync(async (): Promise<BootState> => {
    const { deps, skew } = await resolveDeps();
    if (!deps.ready) return { kind: "deps_missing", deps };

    // Nested deps on git-status (newer servers) can still hard-block.
    let git: GitSyncStatus;
    try {
      git = await api.gitStatus(true);
    } catch (e) {
      if (isHttpStatus(e, 404)) {
        // Very old backend: skip git gate too and try overview only.
        const overview = await api.overview();
        return {
          kind: "ready",
          git: {
            ok: true,
            status: "skipped",
            update_required: false,
            message: "git-status unavailable on this backend",
          },
          overview,
          deps,
          backendSkew: true,
        };
      }
      throw e;
    }

    const nested = git.deps;
    if (nested && nested.ready === false) {
      return { kind: "deps_missing", deps: nested };
    }
    if (git.update_required) return { kind: "update_required", git };

    const overview = await api.overview();
    return { kind: "ready", git, overview, deps, backendSkew: skew };
  }, []);

  if (boot.status === "loading") {
    return (
      <div className={styles.center}>
        <span className={styles.spinner} aria-hidden />
        <span className={styles.centerText}>Checking environment…</span>
      </div>
    );
  }

  if (boot.status === "error") {
    const msg = boot.error.message || "";
    const looks404 = /\bHTTP 404\b/.test(msg);
    return (
      <div className={styles.center}>
        <span className={styles.errorTitle}>
          {looks404 ? "Backend API mismatch" : "Can’t start the evaluation UI"}
        </span>
        <span className={styles.centerText}>
          {looks404 ? (
            <>
              The UI called an API route this backend does not have ({msg}).
              Usually that means the frontend and <code>server.py</code> are from
              different clones or the server was not restarted after{" "}
              <code>git pull</code>.
            </>
          ) : (
            <>
              {msg || "Failed to reach the evaluation API."} Start the backend
              with <code>python3 server.py</code> (serves :8420) from the{" "}
              <strong>same repo</strong> as this UI, then retry.
            </>
          )}
        </span>
        <pre className={styles.centerCode}>
          {`# from the repo that serves this UI
git pull --ff-only
python3 -m pip install -r requirements.txt
python3 tools/check_deps.py
# free port 8420 if an old server is stuck:
#   lsof -iTCP:8420 -sTCP:LISTEN
python3 server.py
# and restart Vite from the SAME directory:
npm --prefix web run dev`}
        </pre>
        <button type="button" className={styles.retry} onClick={boot.reload}>
          Retry
        </button>
      </div>
    );
  }

  if (boot.data.kind === "deps_missing") {
    return <DepsMissingScreen deps={boot.data.deps} onRetry={boot.reload} />;
  }

  if (boot.data.kind === "update_required") {
    return <UpdateRequiredScreen git={boot.data.git} onRetry={boot.reload} />;
  }

  const overview = boot.data.overview;
  if (isEmpty(overview)) {
    return <Onboarding onSeeded={boot.reload} />;
  }

  return (
    <>
      {boot.data.backendSkew && (
        <div className={styles.skewBanner} role="status">
          Backend is older than this UI (missing deps API). App continues, but
          restart <code>python3 server.py</code> from the same clone after{" "}
          <code>git pull</code> for full checks.
        </div>
      )}
      <AppRoutes />
    </>
  );
}
