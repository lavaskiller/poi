import { NavLink } from "react-router-dom";
import styles from "./Sidebar.module.css";

const WORKFLOW = [
  { to: "/", label: "Home", end: true },
  { to: "/new-run", label: "New run" },
  { to: "/results", label: "Results" },
  { to: "/compare", label: "Compare" },
];

const DATA = [
  { to: "/datasets", label: "Datasets" },
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
        <span className={styles.statusText}>API connected · 3 datasets</span>
      </div>
    </aside>
  );
}
