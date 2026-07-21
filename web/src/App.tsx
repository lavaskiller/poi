import { Routes, Route, Outlet } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Home from "./pages/Home";
import NewRun from "./pages/NewRun";
import Results from "./pages/Results";
import CaseInspector from "./pages/CaseInspector";
import Compare from "./pages/Compare";
import Datasets from "./pages/Datasets";
import RetrievalDiagnostics from "./pages/RetrievalDiagnostics";
import Onboarding from "./pages/Onboarding";
import Placeholder from "./pages/Placeholder";
import { api, isEmpty } from "./lib/api";
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
        <Route path="retrieval" element={<RetrievalDiagnostics />} />
        <Route path="jobs" element={<Placeholder title="Jobs" />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  const overview = useAsync(() => api.overview(), []);

  if (overview.status === "loading") {
    return (
      <div className={styles.center}>
        <span className={styles.spinner} aria-hidden />
        <span className={styles.centerText}>Connecting to the evaluation API…</span>
      </div>
    );
  }

  if (overview.status === "error") {
    return (
      <div className={styles.center}>
        <span className={styles.errorTitle}>Can’t reach the evaluation server</span>
        <span className={styles.centerText}>
          Start the backend with <code>python3 server.py</code> (serves :8420), then retry.
        </span>
        <button type="button" className={styles.retry} onClick={overview.reload}>
          Retry
        </button>
      </div>
    );
  }

  if (isEmpty(overview.data)) {
    return <Onboarding onSeeded={overview.reload} />;
  }

  return <AppRoutes />;
}
