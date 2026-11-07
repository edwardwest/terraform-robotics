"use client";
// Step 5: interventions from the catalog, ranked against the goals brief and the site, to add to the plan.
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api, type Fit, type InterventionCategory, type PlanItem, type Project, type Recommendation, type Recommendations,
} from "@/lib/api";
import { INTERVIEW_PROMPT, useAssistant, useAssistantPage } from "@/lib/assistant";
import { formatQuantity, optionLabel, quantityUnit, tierLabel, useCatalog } from "@/lib/catalog";
import { PROJECT_CHANGED, announceChange, stepCount, type ProjectChange } from "@/lib/steps";
import { formatAcres, formatPct } from "@/lib/units";
import { IconAlert, IconArrowRight, IconCheck, IconPlus } from "../Icons";
import styles from "./IdeasView.module.css";

const GROUPS: { fit: Fit; title: string; note: string }[] = [
  { fit: "good", title: "Good fit", note: "Serves your goals and suits the site as far as the app can tell." },
  { fit: "possible", title: "Worth a look", note: "Fits, with a concern to weigh, or serves goals you didn't pick." },
  { fit: "not_suited", title: "Not suited here", note: "A hard requirement is missing on this site." },
];

const UPKEEP: Record<string, string> = { low: "Low upkeep", medium: "Medium upkeep", high: "High upkeep" };

export function IdeasView({ projectId }: { projectId: string }) {
  const { catalog, error: catalogError } = useCatalog();
  const { ask } = useAssistant();
  const [project, setProject] = useState<Project | null>(null);
  const [recs, setRecs] = useState<Recommendations | null>(null);
  const [plan, setPlan] = useState<Record<string, PlanItem>>({});
  const [filter, setFilter] = useState<InterventionCategory | "all">("all");
  const [showUnsuited, setShowUnsuited] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, p] = await Promise.all([api.getRecommendations(projectId), api.getPlan(projectId)]);
      setRecs(r);
      setPlan(Object.fromEntries(p.map((i) => [i.intervention_id, i])));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setError(e.message));
    load();
  }, [projectId, load]);

  useEffect(() => {
    const on = (e: Event) => {
      const what = (e as CustomEvent<ProjectChange>).detail;
      if (what === "brief" || what === "plan") load();
    };
    window.addEventListener(PROJECT_CHANGED, on);
    return () => window.removeEventListener(PROJECT_CHANGED, on);
  }, [load]);

  const items = useMemo(
    () => (recs?.items ?? []).filter((r) => filter === "all" || r.category === filter),
    [recs, filter],
  );
  const planList = useMemo(
    () => (recs?.items ?? []).filter((r) => plan[r.id]).map((r) => ({ r, p: plan[r.id] })),
    [recs, plan],
  );

  useAssistantPage("ideas", {
    page: "Ideas",
    brief_complete: recs ? recs.brief_complete : null,
    has_terrain: recs?.site.has_terrain ?? null,
    category_filter: filter,
    good_fit: recs?.items.filter((r) => r.fit === "good").map((r) => r.id).slice(0, 12),
    in_plan: Object.keys(plan),
  });

  const toggle = async (r: Recommendation) => {
    setBusy(r.id);
    setError(null);
    try {
      if (plan[r.id]) {
        await api.removePlanItem(projectId, r.id);
        setPlan(({ [r.id]: _, ...rest }) => rest);
      } else {
        const item = await api.putPlanItem(projectId, r.id);
        setPlan((m) => ({ ...m, [r.id]: item }));
      }
      announceChange("plan");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const setQuantity = async (id: string, metric: number) => {
    try {
      const item = await api.putPlanItem(projectId, id, { quantity: metric });
      setPlan((m) => ({ ...m, [id]: item }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const site = recs?.site;

  return (
    <div className={styles.layout}>
      <header className={styles.head}>
        <p className="app-eyebrow">
          {project ? `${project.name} · ${formatAcres(project.area_m2)} acres · ` : ""}{stepCount("ideas")}
        </p>
        <h1 className="app-display">Interventions that fit this land.</h1>
        <p className="app-body">
          Ranked against your goals and what the app knows about the site. Add the ones you want to your plan; the
          Design step puts them in build order.
        </p>
      </header>

      <div className={styles.main}>
        {recs && !recs.brief_complete && (
          <div className={`card ${styles.banner}`} role="status">
            <p className="app-body">No goals yet, so these aren&apos;t ranked for you.</p>
            <div className={styles.bannerActions}>
              <Link href={`/projects/${projectId}/goals`} className="btn btn-sm btn-primary">Set your goals</Link>
              <button type="button" className="btn btn-sm" onClick={() => ask(INTERVIEW_PROMPT)}>Talk it through</button>
            </div>
          </div>
        )}
        {site && (
          <p className="app-small">
            {site.has_terrain
              ? `Checked against the terrain model: average slope ${formatPct(site.mean_slope_pct)}, ${site.main_valleys ?? 0} main valley${site.main_valleys === 1 ? "" : "s"}, ${site.keypoint_count ?? 0} keypoint${site.keypoint_count === 1 ? "" : "s"}.`
              : "No terrain model yet, so slope and valley checks are left open. Build it on the Survey step to sharpen these."}
          </p>
        )}

        <div className={styles.filters} role="toolbar" aria-label="Filter by category">
          <button type="button" className="chip" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
          {catalog?.categories.map((c) => (
            <button key={c.id} type="button" className="chip" aria-pressed={filter === c.id} onClick={() => setFilter(c.id)}>
              {c.label}
            </button>
          ))}
        </div>

        {(error || catalogError) && <p className="error-text" role="alert">{error || catalogError}</p>}
        {!recs && !error && <div className="progress progress-indeterminate" aria-label="Loading ideas"><span /></div>}

        {recs && GROUPS.map((g) => {
          const list = items.filter((r) => r.fit === g.fit);
          if (!list.length) return null;
          const collapsed = g.fit === "not_suited" && !showUnsuited;
          return (
            <section key={g.fit} className={styles.group} aria-labelledby={`fit-${g.fit}`}>
              <div className={styles.groupHead}>
                <div>
                  <h2 className={styles.groupTitle} id={`fit-${g.fit}`}>{g.title} <span className={styles.count}>{list.length}</span></h2>
                  <p className="app-small">{g.note}</p>
                </div>
                {g.fit === "not_suited" && (
                  <button type="button" className="btn btn-sm btn-ghost" aria-expanded={!collapsed}
                    onClick={() => setShowUnsuited((v) => !v)}>
                    {collapsed ? "Show" : "Hide"}
                  </button>
                )}
              </div>
              {!collapsed && (
                <ul className={styles.cards}>
                  {list.map((r) => (
                    <IdeaCard key={r.id} r={r} planItem={plan[r.id] ?? null} busy={busy === r.id} projectId={projectId}
                      categoryLabel={optionLabel(catalog, "categories", r.category)}
                      phaseLabel={optionLabel(catalog, "phases", r.phase)}
                      onToggle={() => toggle(r)} onQuantity={(m) => setQuantity(r.id, m)} />
                  ))}
                </ul>
              )}
            </section>
          );
        })}

        {recs && (
          <footer className={styles.foot}>
            <span className="app-small">
              {planList.length === 0
                ? "Add the ideas you want, then lay them out in build order."
                : `${planList.length} idea${planList.length === 1 ? "" : "s"} in your plan. The Design step puts them in build order.`}
            </span>
            <Link href={`/projects/${projectId}/design`} className="btn btn-primary">
              Continue to design <IconArrowRight />
            </Link>
          </footer>
        )}
      </div>

      <aside className={styles.side} aria-labelledby="plan-h">
        <div className={`card ${styles.planCard}`}>
          <p className="app-eyebrow" id="plan-h">
            Your plan{planList.length > 0 && <span className={styles.planCount}> · {planList.length}</span>}
          </p>
          {planList.length === 0 ? (
            <p className="app-small">Nothing yet. Use Add to plan on the ideas you want.</p>
          ) : (
            <ul className={styles.planList}>
              {planList.map(({ r, p }) => (
                <li key={r.id}>
                  <span>{r.title}</span>
                  <span className="app-small">
                    {r.tool ? "Laid out on the Design step" : formatQuantity(p.quantity_basis, p.quantity)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className={styles.planFoot}>
            <Link href={`/projects/${projectId}/design`} className={`btn btn-primary ${styles.next}`}>
              Continue to design <IconArrowRight />
            </Link>
          </div>
        </div>
      </aside>
    </div>
  );
}

function IdeaCard({ r, planItem, busy, projectId, categoryLabel, phaseLabel, onToggle, onQuantity }: {
  r: Recommendation;
  planItem: PlanItem | null;
  busy: boolean;
  projectId: string;
  categoryLabel: string;
  phaseLabel: string;
  onToggle: () => void;
  onQuantity: (metric: number) => void;
}) {
  const inPlan = !!planItem;
  const basis = r.quantity?.basis ?? null;
  const metric = planItem?.quantity ?? r.quantity?.default ?? null;
  // Keep the display unit steady while typing: choose it from the catalog default, not the live value.
  const unit = basis ? quantityUnit(basis, r.quantity?.default ?? null) : null;
  const shown = unit && metric != null ? String(Number(unit.toDisplay(metric).toFixed(unit.unit === "acres" ? 2 : 0))) : "";
  const [qty, setQty] = useState(shown);
  useEffect(() => setQty(shown), [shown]);

  const commit = () => {
    const v = parseFloat(qty);
    if (!unit || !Number.isFinite(v) || v < 0) {
      setQty(shown);
      return;
    }
    if (String(v) !== shown) onQuantity(unit.toMetric(v));
  };

  return (
    <li className={`card ${styles.card} ${inPlan ? "card-selected" : ""}`}>
      <div className={styles.cardHead}>
        <div>
          <h3 className={styles.cardTitle}>{r.title}</h3>
          <p className="app-small">
            {categoryLabel} · {phaseLabel} phase · {UPKEEP[r.maintenance]} · <span title="Cost tier">{tierLabel(r.cost_tier)}</span>
          </p>
        </div>
        {r.fit !== "not_suited" || inPlan ? (
          <button type="button" className={`btn btn-sm ${inPlan ? "" : "btn-primary"}`} aria-pressed={inPlan}
            onClick={onToggle} disabled={busy}>
            {inPlan ? <><IconCheck size={14} /> In plan</> : <><IconPlus size={14} /> Add to plan</>}
          </button>
        ) : null}
      </div>
      <p className={styles.summaryText}>{r.summary}</p>

      {(r.reasons.length > 0 || r.concerns.length > 0) && (
        <ul className={styles.points}>
          {r.reasons.map((t) => <li key={t}><IconCheck size={14} /> <span>{t}</span></li>)}
          {r.concerns.map((t) => <li key={t} className={styles.concern}><IconAlert size={14} /> <span>{t}</span></li>)}
        </ul>
      )}
      {r.unknowns.map((t) => <p key={t} className={`app-small ${styles.unknown}`}>{t}</p>)}

      {r.cautions.length > 0 && (
        <details className={styles.more}>
          <summary className="app-small">Permits and safety</summary>
          <ul className={styles.cautions}>
            {r.cautions.map((c) => <li key={c} className="app-small">{c}</li>)}
          </ul>
        </details>
      )}

      {(r.nrcs.length > 0 || r.references.length > 0) && (
        <p className={`app-small ${styles.refs}`}>
          {r.nrcs.length > 0 && <span>NRCS practice {r.nrcs.join(", ")}</span>}
          {r.references.length > 0 && (
            <span>
              Further reading:{" "}
              {r.references.map((ref, i) => (
                <span key={ref.id}>
                  {i > 0 && "; "}
                  {ref.url && /^https:\/\//.test(ref.url)
                    ? <a href={ref.url} target="_blank" rel="noreferrer">{ref.title}</a>
                    : ref.title}
                </span>
              ))}
            </span>
          )}
        </p>
      )}

      {r.tool && r.fit !== "not_suited" && (
        <Link href={`/projects/${projectId}/design?tool=${r.tool}`} className={styles.toolLink}>
          Lay out on the Design step <IconArrowRight size={14} />
        </Link>
      )}
      {inPlan && unit && r.has_allowance && (
        <label className={styles.qty}>
          <span className="field-label">How much</span>
          <span className={styles.qtyRow}>
            <input className="input" type="number" min={0} inputMode="decimal" value={qty}
              onChange={(e) => setQty(e.target.value)} onBlur={commit}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              aria-label={`${r.title} quantity${unit.unit ? ` in ${unit.unit}` : ""}`} />
            <span className="app-small">{unit.unit || "count"} · for the estimate</span>
          </span>
        </label>
      )}
    </li>
  );
}
