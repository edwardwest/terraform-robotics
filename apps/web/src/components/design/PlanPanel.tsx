"use client";
// The plan on the Design step: chosen interventions in build order (Yeomans' scale of permanence). Keyline and
// swale entries open the matching tool; the rest are carried into the estimate as planning allowances.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type PlanItem } from "@/lib/api";
import { formatQuantity, optionLabel, useCatalog } from "@/lib/catalog";
import { PROJECT_CHANGED, type ProjectChange } from "@/lib/steps";
import styles from "./DesignView.module.css";

export function PlanPanel({ projectId, onTool, onCount }: {
  projectId: string;
  onTool: (tool: "keyline" | "swale") => void;
  onCount?: (n: number) => void;
}) {
  const { catalog } = useCatalog();
  const [plan, setPlan] = useState<PlanItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.getPlan(projectId).then((p) => {
      setPlan(p);
      onCount?.(p.length);
    }).catch((e: Error) => setError(e.message));
  }, [projectId, onCount]);

  useEffect(load, [load]);
  useEffect(() => {
    const on = (e: Event) => {
      if ((e as CustomEvent<ProjectChange>).detail === "plan") load();
    };
    window.addEventListener(PROJECT_CHANGED, on);
    return () => window.removeEventListener(PROJECT_CHANGED, on);
  }, [load]);

  let lastPhase = "";
  return (
    <section className={`card ${styles.plan}`} aria-labelledby="plan-title">
      <div className={styles.planHead}>
        <p className="app-eyebrow" id="plan-title">Your plan</p>
        <Link href={`/projects/${projectId}/ideas`} className="btn btn-sm btn-ghost">Edit plan</Link>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {plan && plan.length === 0 && (
        <p className="app-small">
          Nothing chosen yet. <Link href={`/projects/${projectId}/ideas`}>Pick interventions on the Ideas step</Link>, or
          use the keyline and swale tools below.
        </p>
      )}
      {plan && plan.length > 0 && (
        <ol className={styles.planList}>
          {plan.map((p) => {
            const showPhase = p.phase !== lastPhase;
            lastPhase = p.phase;
            return (
              <li key={p.intervention_id}>
                {showPhase && <span className={`field-label ${styles.planPhase}`}>{optionLabel(catalog, "phases", p.phase)}</span>}
                <span className={styles.planRow}>
                  <span className={styles.planText}>
                    <span className={styles.planTitle}>{p.title}</span>
                    <span className="app-small">
                      {p.tool ? "Computed from the terrain model" : `${formatQuantity(p.quantity_basis, p.quantity)} · allowance in the estimate`}
                    </span>
                  </span>
                  {p.tool && (
                    <button type="button" className="btn btn-sm" onClick={() => onTool(p.tool!)}>Lay out</button>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
