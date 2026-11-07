"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, exportUrl, type CostItem, type Estimate, type Project } from "@/lib/api";
import { IconAlert, IconArrowLeft, IconArrowRight, IconDownload } from "../Icons";
import styles from "./Estimate.module.css";

const usd = (n: number, digits = 0) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const range = (lo: number, hi: number) => (Math.round(lo) === Math.round(hi) ? usd(lo) : `${usd(lo)} – ${usd(hi)}`);
const num = (n: number, d = 0) => n.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const rate = (lo: number, hi: number) => {
  const d = Math.min(lo, hi) < 10 && (lo % 1 || hi % 1) ? 2 : 0;
  return lo === hi ? usd(lo, d) : `${usd(lo, d)} – ${usd(hi, d)}`;
};
const plural = (unit: string, q: number) => {
  if (q === 1) return unit;
  if (unit.endsWith("foot")) return unit.replace(/foot$/, "feet");
  return `${unit}s`;
};

export function EstimateView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [costs, setCosts] = useState<Record<string, CostItem>>({});
  const [contingency, setContingency] = useState(15);
  const [editing, setEditing] = useState(false);
  const [draftRates, setDraftRates] = useState<Record<string, { lo: string; hi: string }>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (pct: number) => {
    try {
      const [e, c] = await Promise.all([api.getEstimate(projectId, pct), api.listCostItems()]);
      setEstimate(e);
      setCosts(Object.fromEntries(c.map((i) => [i.item, i])));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setError(e.message));
  }, [projectId]);
  useEffect(() => {
    const t = setTimeout(() => load(contingency), 250);
    return () => clearTimeout(t);
  }, [load, contingency]);

  const startEdit = () => {
    setDraftRates(Object.fromEntries(Object.values(costs).map((c) => [c.item, { lo: String(c.rate_low), hi: String(c.rate_high) }])));
    setEditing(true);
  };

  const saveRates = async () => {
    setSaving(true);
    setError(null);
    try {
      for (const [item, v] of Object.entries(draftRates)) {
        const c = costs[item];
        const lo = parseFloat(v.lo);
        const hi = parseFloat(v.hi);
        if (!c || !Number.isFinite(lo) || !Number.isFinite(hi)) continue;
        if (lo !== c.rate_low || hi !== c.rate_high) await api.updateCostItem(item, lo, hi);
      }
      setEditing(false);
      await load(contingency);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const reset = async (item: string) => {
    await api.resetCostItem(item);
    await load(contingency);
    setEditing(false);
  };

  const q = estimate?.quantities;
  const empty = estimate && estimate.lines.length === 0;

  return (
    <div className={styles.layout}>
      <header className={styles.head}>
        <p className="app-eyebrow">{project ? `${project.name} · ` : ""}Step 5 of 5 · Estimate</p>
        <h1 className="app-display">What it costs to rehydrate this land.</h1>
      </header>

      <aside className={styles.side}>
        <section className={`card ${styles.total}`} aria-labelledby="total">
          <p className="app-eyebrow" id="total">Total build estimate</p>
          <p className={styles.big}>{estimate ? range(estimate.total_low, estimate.total_high) : "—"}</p>
          <p className="app-small">Earthworks, layout and design, with contingency.</p>
          {estimate?.draft && (
            <p className={`app-small ${styles.draft}`}><IconAlert size={12} /> Design is a draft on planning-grade terrain.</p>
          )}
        </section>
        <section className={`card ${styles.small}`}>
          <p className="field-label">Design fee</p>
          <p className={styles.mid}>{estimate ? range(estimate.design_fee_low, estimate.design_fee_high) : "—"}</p>
          <p className="app-small">Plan set, layout and machine paths, {q ? num(q.site_acres, 1) : "—"} acres.</p>
        </section>
        <section className={`card ${styles.small}`}>
          <label className="field-label" htmlFor="cont">Contingency</label>
          <p className={styles.mid}>{estimate ? range(estimate.contingency_low, estimate.contingency_high) : "—"}</p>
          <div className={styles.inline}>
            <input id="cont" className="input" type="number" min={0} max={100} value={contingency}
              onChange={(e) => setContingency(Math.max(0, Math.min(100, Number(e.target.value) || 0)))} />
            <span className="app-small">% of build</span>
          </div>
        </section>
        {q && (
          <section className={`card ${styles.small}`}>
            <p className="field-label">Field time (planning)</p>
            <p className="app-small">Tractor: about {num(q.tractor_days, 1)} days. Excavator: about {num(q.excavator_days, 1)} days.</p>
            {q.swale_storage_gal > 0 && <p className="app-small">Swales hold about {num(q.swale_storage_gal)} gallons per fill.</p>}
          </section>
        )}
      </aside>

      <section className={`card ${styles.items}`} aria-labelledby="items">
        <div className={styles.itemsHead}>
          <div>
            <p className="app-eyebrow" id="items">Line items</p>
            <p className="app-small">Quantities computed from the design geometry.</p>
          </div>
          {!editing ? (
            <button type="button" className="btn btn-sm" onClick={startEdit} disabled={!estimate}>Edit unit costs</button>
          ) : (
            <div className={styles.inline}>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
              <button type="button" className="btn btn-sm btn-primary" onClick={saveRates} disabled={saving}>{saving ? "Saving." : "Save rates"}</button>
            </div>
          )}
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        {empty && (
          <p className="app-body">No design elements yet. <Link href={`/projects/${projectId}/design`}>Lay out keylines or swales</Link> first.</p>
        )}
        {estimate && !empty && (
          <table className={styles.table}>
            <thead>
              <tr><th>Item</th><th>Quantity</th><th>Unit cost</th><th className={styles.right}>Total</th></tr>
            </thead>
            <tbody>
              {estimate.lines.map((ln) => {
                const c = costs[ln.item];
                return (
                  <tr key={ln.item}>
                    <td>
                      <span className={styles.itemLabel}>{ln.label}</span>
                      <span className="app-small">{ln.basis}</span>
                    </td>
                    <td>{num(ln.quantity, Number.isInteger(ln.quantity) || ln.quantity >= 10 ? 0 : 1)} {plural(ln.unit, ln.quantity)}</td>
                    <td>
                      {editing && draftRates[ln.item] ? (
                        <span className={styles.rateEdit}>
                          <input className="input" aria-label={`${ln.label} low rate`} value={draftRates[ln.item].lo}
                            onChange={(e) => setDraftRates((d) => ({ ...d, [ln.item]: { ...d[ln.item], lo: e.target.value } }))} />
                          <span>–</span>
                          <input className="input" aria-label={`${ln.label} high rate`} value={draftRates[ln.item].hi}
                            onChange={(e) => setDraftRates((d) => ({ ...d, [ln.item]: { ...d[ln.item], hi: e.target.value } }))} />
                          {c?.custom && <button type="button" className="btn btn-sm btn-ghost" onClick={() => reset(ln.item)}>Reset</button>}
                        </span>
                      ) : (
                        <>
                          {rate(ln.rate_low, ln.rate_high)} / {ln.unit}
                          {c?.custom && <span className="app-small"> · yours</span>}
                        </>
                      )}
                    </td>
                    <td className={styles.right}>{range(ln.total_low, ln.total_high)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr><td colSpan={3}>Build subtotal</td><td className={styles.right}>{range(estimate.build_low, estimate.build_high)}</td></tr>
              <tr><td colSpan={3}>Design fee</td><td className={styles.right}>{range(estimate.design_fee_low, estimate.design_fee_high)}</td></tr>
              <tr><td colSpan={3}>Contingency ({estimate.contingency_pct}%)</td><td className={styles.right}>{range(estimate.contingency_low, estimate.contingency_high)}</td></tr>
              <tr className={styles.totalRow}><td colSpan={3}>Total build estimate</td><td className={styles.right}>{range(estimate.total_low, estimate.total_high)}</td></tr>
            </tfoot>
          </table>
        )}
        <p className="app-small">{estimate?.note ?? ""}</p>
      </section>

      <footer className={styles.foot}>
        <Link href={`/projects/${projectId}/design`} className="btn btn-ghost"><IconArrowLeft /> Back to design</Link>
        <a href={exportUrl.estimateXlsx(projectId, contingency)} className={`btn ${empty ? styles.off : ""}`} download>
          <IconDownload size={16} /> Spreadsheet
        </a>
        <Link href={`/projects/${projectId}/export`} className="btn btn-primary">Export plans <IconArrowRight /></Link>
      </footer>
    </div>
  );
}
