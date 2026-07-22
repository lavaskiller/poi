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
import { api, isEmpty, type GitSyncStatus, type Overview } from "./lib/api";
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
  | { kind: "update_required"; git: GitSyncStatus }
  | { kind: "ready"; git: GitSyncStatus; overview: Overview };

function UpdateRequiredScreen({
  git,
  onRetry,
}: {
  git: GitSyncStatus;
  onRetry: () => void;
}) {
  const cmds = git.commands?.length
    ? git.commands
    : ["git pull --ff-only", "# then restart: python3 server.py"];
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
      <pre className={styles.centerCode}>{cmds.join("\n")}</pre>
      {git.hint && <span className={styles.centerText}>{git.hint}</span>}
      <button type="button" className={styles.retry} onClick={onRetry}>
        Re-check after pull
      </button>
    </div>
  );
}

export default function App() {
  // On every open: fetch + compare to upstream; block the SPA when behind.
  const boot = useAsync(async (): Promise<BootState> => {
    const git = await api.gitStatus(true);
    if (git.update_required) return { kind: "update_required", git };
    const overview = await api.overview();
    return { kind: "ready", git, overview };
  }, []);

  if (boot.status === "loading") {
    return (
      <div className={styles.center}>
        <span className={styles.spinner} aria-hidden />
        <span className={styles.centerText}>Checking for code updates…</span>
      </div>
    );
  }

  if (boot.status === "error") {
    return (
      <div className={styles.center}>
        <span className={styles.errorTitle}>Can’t start the evaluation UI</span>
        <span className={styles.centerText}>
          {boot.error.message || "Failed to reach the evaluation API."} Start the
          backend with <code>python3 server.py</code> (serves :8420), then retry.
        </span>
        <button type="button" className={styles.retry} onClick={boot.reload}>
          Retry
        </button>
      </div>
    );
  }

  if (boot.data.kind === "update_required") {
    return <UpdateRequiredScreen git={boot.data.git} onRetry={boot.reload} />;
  }

  const overview = boot.data.overview;
  if (isEmpty(overview)) {
    return <Onboarding onSeeded={boot.reload} />;
  }

  return <AppRoutes />;
}
