"use client";
// Zones and sectors: permaculture zone rings around the house, the sun's path at the solstices (computed from the
// latitude), and the winds and fire direction the person knows from the site. Settings save as they change.
import { useRef, useState } from "react";
import { api, type PlanSite, type PlanSiteSettings, type Wind } from "@/lib/api";
import { ftToM, mToFt } from "@/lib/units";
import { IconPlus, IconX } from "../Icons";
import tv from "../terrain/TerrainView.module.css";
import styles from "./MasterPlan.module.css";

const POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
export const compass = (deg: number) => POINTS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];

export function SitePanel({ projectId, site, onChange }: { projectId: string; site: PlanSite; onChange: (s: PlanSite) => void }) {
  const [draft, setDraft] = useState<PlanSiteSettings>(site.settings);
  const [radii, setRadii] = useState(site.settings.zone_radii_m.map((m) => String(Math.round(mToFt(m)))));
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const save = (next: PlanSiteSettings, delay = 400) => {
    setDraft(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        onChange(await api.putPlanSite(projectId, next));
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      }
    }, delay);
  };

  const setRadius = (i: number, v: string) => {
    const nextText = radii.map((r, j) => (j === i ? v : r));
    setRadii(nextText);
    const ft = nextText.map(Number);
    if (ft.some((x) => !Number.isFinite(x) || x <= 0)) return setError("Enter each zone's distance in feet.");
    if (ft.some((x, j) => j > 0 && x <= ft[j - 1])) return setError("Each zone reaches farther than the one before it.");
    save({ ...draft, zone_radii_m: ft.map((x) => Math.round(ftToM(x) * 10) / 10) as PlanSiteSettings["zone_radii_m"] }, 700);
  };

  const setWind = (i: number, w: Partial<Wind>) =>
    save({ ...draft, winds: draft.winds.map((x, j) => (j === i ? { ...x, ...w } : x)) }, w.label !== undefined ? 700 : 0);

  const sun = site.sun;
  return (
    <section className={`card ${tv.panel} ${styles.site}`} aria-labelledby="site-title">
      <p className="app-eyebrow" id="site-title">Zones and sectors</p>
      <div className={styles.chips}>
        <button type="button" className="chip" aria-pressed={draft.show_zones} onClick={() => save({ ...draft, show_zones: !draft.show_zones }, 0)}>Zones</button>
        <button type="button" className="chip" aria-pressed={draft.show_sectors} onClick={() => save({ ...draft, show_sectors: !draft.show_sectors }, 0)}>Sectors</button>
      </div>
      <p className="app-small">
        {site.center_source === "house" ? "Measured from the house." : "Draw the house to center the zones on it; until then they start at the middle of the property."}
      </p>

      <fieldset className={styles.group}>
        <legend className="field-label">Zone distances from the house (ft)</legend>
        <div className={styles.zoneGrid}>
          {radii.map((r, i) => (
            <label key={i} className={styles.zoneField}>
              <span className="app-small">Zone {i + 1}</span>
              <input className="input" inputMode="numeric" value={r} onChange={(e) => setRadius(i, e.target.value)} aria-label={`Zone ${i + 1} reaches (ft)`} />
            </label>
          ))}
        </div>
        <p className="app-small">Zone 5, the wild zone, is everything beyond zone 4.</p>
      </fieldset>

      {sun && (
        <div className={styles.group}>
          <p className="field-label">Sun</p>
          {sun.summer && (
            <p className="app-small">June: rises {compass(sun.summer.rise)} ({Math.round(sun.summer.rise)}°), sets {compass(sun.summer.set)}, {Math.round(sun.summer.noon_altitude)}° high at noon.</p>
          )}
          {sun.winter && (
            <p className="app-small">December: rises {compass(sun.winter.rise)} ({Math.round(sun.winter.rise)}°), sets {compass(sun.winter.set)}, {Math.round(sun.winter.noon_altitude)}° high at noon.</p>
          )}
        </div>
      )}

      <fieldset className={styles.group}>
        <legend className="field-label">Winds</legend>
        {draft.winds.map((w, i) => (
          <div key={i} className={styles.windRow}>
            <input className="input" maxLength={40} value={w.label} onChange={(e) => setWind(i, { label: e.target.value })} aria-label="Wind name" />
            <select className="input" value={Math.round(w.from_deg / 22.5) % 16} onChange={(e) => setWind(i, { from_deg: Number(e.target.value) * 22.5 })} aria-label="Comes from">
              {POINTS.map((p, j) => <option key={p} value={j}>from {p}</option>)}
            </select>
            <button type="button" className="icon-btn" aria-label={`Remove ${w.label}`} onClick={() => save({ ...draft, winds: draft.winds.filter((_, j) => j !== i) }, 0)}>
              <IconX size={14} />
            </button>
          </div>
        ))}
        {draft.winds.length < 4 && (
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => save({ ...draft, winds: [...draft.winds, { label: draft.winds.length ? "Winter storms" : "Prevailing wind", from_deg: 270 }] }, 0)}>
            <IconPlus size={14} /> Add a wind
          </button>
        )}
      </fieldset>

      <div className="field">
        <label className="field-label" htmlFor="site-fire">Wildfire most likely from</label>
        <select id="site-fire" className="input" value={draft.fire_from_deg == null ? "" : Math.round(draft.fire_from_deg / 22.5) % 16}
          onChange={(e) => save({ ...draft, fire_from_deg: e.target.value === "" ? null : Number(e.target.value) * 22.5 }, 0)}>
          <option value="">Not set</option>
          {POINTS.map((p, j) => <option key={p} value={j}>{p}</option>)}
        </select>
        <p className="app-small">Often uphill, or the direction of hot, dry wind in fire season. Your local fire agency can tell you.</p>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  );
}
