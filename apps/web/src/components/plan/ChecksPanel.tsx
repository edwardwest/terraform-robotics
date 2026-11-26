"use client";
// Placement checks: guidance from rules in code (each with its source), not approvals.
import type { PlanChecks, PlanFinding } from "@/lib/api";
import { mToFt } from "@/lib/units";
import { IconAlert } from "../Icons";
import tv from "../terrain/TerrainView.module.css";
import styles from "./MasterPlan.module.css";

function measure(m: PlanFinding["measure"]): string | null {
  if (m.grade_pct != null) return `${Math.round(m.grade_pct)}% grade`;
  if (m.slope_pct != null) return `${Math.round(m.slope_pct)}% average slope`;
  if (m.drop_m != null && m.distance_m != null) return `${Math.round(mToFt(m.drop_m))} ft higher, ${Math.round(mToFt(m.distance_m))} ft away`;
  if (m.distance_m != null) return `${Math.round(mToFt(m.distance_m))} ft away`;
  if (m.angle_deg != null) return `${Math.round(m.angle_deg)}° off the wind`;
  return null;
}

export function ChecksPanel({ checks, onSelect }: { checks: PlanChecks | null; onSelect: (featureId: string) => void }) {
  if (!checks) return null;
  const warnings = checks.findings.filter((f) => f.severity === "warning").length;
  return (
    <section className={`card ${tv.panel}`} aria-labelledby="checks-title">
      <p className="app-eyebrow" id="checks-title">
        Checks{checks.findings.length > 0 ? ` · ${warnings} warning${warnings === 1 ? "" : "s"}, ${checks.findings.length - warnings} note${checks.findings.length - warnings === 1 ? "" : "s"}` : ""}
      </p>
      {checks.findings.length === 0 && <p className="app-small">Nothing to flag in the placement so far.</p>}
      <ul className={styles.checkList}>
        {checks.findings.map((f, i) => (
          <li key={`${f.rule}-${i}`}>
            <button type="button" className={styles.check2} onClick={() => f.feature_ids[0] && onSelect(f.feature_ids[0])}>
              <span className={styles.checkHead}>
                {f.severity === "warning" && <IconAlert size={14} />}
                <span className={styles.itemTitle}>{f.title}</span>
                <span className={`app-small ${styles.severity}`}>{f.severity === "warning" ? "Warning" : "Note"}</span>
              </span>
              <span className="app-small">{f.message}</span>
              {measure(f.measure) && <span className="app-small">{measure(f.measure)}</span>}
              <span className={`app-small ${styles.source}`}>{f.source}</span>
            </button>
          </li>
        ))}
      </ul>
      {!checks.terrain && <p className="app-small">Add a terrain model to also check runoff direction, pond slopes and road grades.</p>}
      <p className="app-small">Guidance, not approval: check county rules before building.</p>
    </section>
  );
}
