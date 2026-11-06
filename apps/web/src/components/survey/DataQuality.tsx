import type { Survey, TerrainSummary } from "@/lib/api";
import { formatPct, formatResolution } from "@/lib/units";
import styles from "./DataQuality.module.css";

const ROWS = [
  { key: "design_pct", label: "Design grade", note: "1 m or finer.", swatch: "design" },
  { key: "planning_pct", label: "Planning grade", note: "Up to 10 m.", swatch: "planning" },
  { key: "coarse_pct", label: "Too coarse", note: "Over 10 m.", swatch: "coarse" },
] as const;

export function DataQuality({ surveys, terrain }: { surveys: Survey[]; terrain: TerrainSummary | null }) {
  const q = terrain?.quality;
  const finest = surveys
    .map((s) => s.resolution_m)
    .filter((r): r is number => r != null)
    .sort((a, b) => a - b)[0];

  return (
    <aside className={`card ${styles.aside}`} aria-labelledby="dq-title">
      <p className="app-eyebrow">Data quality</p>
      {q ? (
        <>
          <h2 id="dq-title" className="app-h2">
            {formatPct(q.design_pct)} of the site is design grade.
          </h2>
          <div className={styles.bar} aria-hidden="true">
            <span className={styles.design} style={{ width: `${q.design_pct}%` }} />
            <span className={styles.planning} style={{ width: `${q.planning_pct}%` }} />
            <span className={styles.coarse} style={{ width: `${q.coarse_pct}%` }} />
          </div>
        </>
      ) : (
        <h2 id="dq-title" className="app-h2">
          {surveys.length ? "Build the terrain model to measure coverage." : "No ground data yet."}
        </h2>
      )}

      <ul className={styles.legend}>
        {ROWS.map((r) => (
          <li key={r.key}>
            <span className={`${styles.swatch} ${styles[r.swatch]}`} aria-hidden="true" />
            <span className={styles.legendText}>
              <span className={styles.legendLabel}>{r.label}</span>
              <span className="app-small">{r.note}</span>
            </span>
            <span className={styles.pct}>{q ? formatPct(q[r.key]) : "—"}</span>
          </li>
        ))}
      </ul>

      <dl className={styles.meta}>
        <div>
          <dt className="field-label">Sources</dt>
          <dd>{surveys.length}</dd>
        </div>
        <div>
          <dt className="field-label">Finest cell</dt>
          <dd>{formatResolution(terrain?.dem_resolution_m ?? finest)}</dd>
        </div>
      </dl>
    </aside>
  );
}
