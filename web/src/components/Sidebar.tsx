import { NavLink } from "react-router-dom";
import { api } from "../lib/api";
import { useRefreshOnFocus } from "../lib/dataRefresh";
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
