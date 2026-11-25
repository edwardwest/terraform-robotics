"use client";
// Properties of a selected master plan feature: type, label, status, build phase, measurements and the settings its
// type takes (species and spacing, building height and roof, storage capacity). Inputs are in feet and gallons;
// the API stores metres and cubic metres.
import { useEffect, useMemo, useState } from "react";
import { api, type PlanFeature, type PlanFeatureSettings, type PlanFeatureUpdate, type PlanLibrary, type Roof, type Species, type SpeciesRef } from "@/lib/api";
import { ftToM, galToM3, m3ToGal } from "@/lib/units";
import { IconPencil, IconX } from "../Icons";
import tv from "../terrain/TerrainView.module.css";
import { feetValue, formatArea, formatLength } from "./format";
import styles from "./MasterPlan.module.css";

const ROOF_LABEL: Record<Roof, string> = { gable: "Gable", hip: "Hip", shed: "Shed", flat: "Flat" };

interface Props {
  feature: PlanFeature;
  library: PlanLibrary;
  onSave: (body: PlanFeatureUpdate) => Promise<void>;
  onDelete: () => void;
  onEditShape: () => void;
  onClose: () => void;
  editingShape: boolean;
}

/** Parse a feet input to metres; empty is null, anything else unparseable is an error. */
function feetToM(v: string): number | null | "bad" {
  if (!v.trim()) return null;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.round(ftToM(n) * 100) / 100 : "bad";
}

export function FeatureProperties({ feature, library, onSave, onDelete, onEditShape, onClose, editingShape }: Props) {
  const p = feature.properties;
  const type = library.types.find((t) => t.id === p.type)!;
  const category = library.categories.find((c) => c.id === p.category);
  const sameShape = useMemo(() => library.types.filter((t) => t.geometry === type.geometry), [library, type]);
  const fields = new Set(type.fields);

  const [typeId, setTypeId] = useState(p.type);
  const [label, setLabel] = useState(p.label ?? "");
  const [status, setStatus] = useState(p.status);
  const [phase, setPhase] = useState(p.build_phase);
  const [species, setSpecies] = useState<SpeciesRef[]>(p.props.species ?? []);
  const [rowFt, setRowFt] = useState(feetValue(p.props.row_spacing_m));
  const [plantFt, setPlantFt] = useState(feetValue(p.props.plant_spacing_m));
  const [rows, setRows] = useState(p.props.rows ? String(p.props.rows) : "");
  const [heightFt, setHeightFt] = useState(feetValue(p.props.height_m));
  const [roof, setRoof] = useState<Roof | undefined>(p.props.roof);
  const [gallons, setGallons] = useState(p.props.capacity_m3 ? String(Math.round(m3ToGal(p.props.capacity_m3))) : "");
  const [notes, setNotes] = useState(p.props.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The panel remounts with the saved feature after each save (its key includes updated_at).
  const save = async () => {
    setError(null);
    if (typeId !== p.type) {
      // A type change resets the settings to the new type's; save it on its own first.
      setSaving(true);
      try {
        await onSave({ type: typeId, label: label === p.type_label || !label ? (library.types.find((t) => t.id === typeId)?.label ?? label) : label });
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setSaving(false);
      }
      return;
    }
    const props: Partial<PlanFeatureSettings> = {};
    if (fields.has("species")) {
      props.species = species;
      for (const [key, v, show] of [
        ["plant_spacing_m", plantFt, type.geometry !== "point"],
        ["row_spacing_m", rowFt, type.geometry === "polygon"],
        ["height_m", heightFt, true],
      ] as const) {
        if (!show) continue;
        const m = feetToM(v);
        if (m === "bad") return setError("Enter spacing and height as numbers of feet.");
        if (m !== null) props[key] = m;
      }
      if (type.geometry === "line" && rows.trim()) {
        const n = Number(rows);
        if (!Number.isInteger(n) || n < 1 || n > 10) return setError("Rows must be a whole number from 1 to 10.");
        props.rows = n;
      }
    }
    if (fields.has("building")) {
      const m = feetToM(heightFt);
      if (m === "bad") return setError("Enter the height as a number of feet.");
      if (m !== null) props.height_m = m;
      if (roof) props.roof = roof;
    }
    if (fields.has("capacity") && gallons.trim()) {
      const g = Number(gallons);
      if (!Number.isFinite(g) || g < 0) return setError("Enter the capacity in gallons.");
      props.capacity_m3 = Math.round(galToM3(g) * 1000) / 1000;
    }
    if (notes.trim()) props.notes = notes.trim();
    setSaving(true);
    try {
      await onSave({ label: label.trim() || type.label, status, build_phase: phase, props });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className={`card ${tv.panel} ${styles.props}`} aria-labelledby="feature-title">
      <div className={styles.propsHead}>
        <span className={styles.swatch} style={{ background: p.color }} aria-hidden="true" />
        <p className="app-eyebrow" id="feature-title">{category?.label} · {p.type_label}</p>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}><IconX size={16} /></button>
      </div>

      {(p.area_m2 != null || p.length_m != null || p.plant_count != null) && (
      <dl className={styles.measures}>
        {p.area_m2 != null && <div><dt className="app-small">Area</dt><dd>{formatArea(p.area_m2)}</dd></div>}
        {p.perimeter_m != null && <div><dt className="app-small">Edge</dt><dd>{formatLength(p.perimeter_m)}</dd></div>}
        {p.length_m != null && <div><dt className="app-small">Length</dt><dd>{formatLength(p.length_m)}</dd></div>}
        {p.plant_count != null && <div><dt className="app-small">Plants</dt><dd>{p.plant_count.toLocaleString("en-US")}</dd></div>}
      </dl>
      )}
      {p.intervention && p.status === "proposed" && type.intervention_title && (
        <p className="app-small">Counts toward {type.intervention_title.toLowerCase()} in your plan and estimate.</p>
      )}

      <div className="field">
        <label className="field-label" htmlFor="pf-type">Type</label>
        <select id="pf-type" className="input" value={typeId} onChange={(e) => setTypeId(e.target.value)}>
          {library.categories.map((c) => {
            const opts = sameShape.filter((t) => t.category === c.id);
            return opts.length ? (
              <optgroup key={c.id} label={c.label}>
                {opts.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </optgroup>
            ) : null;
          })}
        </select>
      </div>

      {typeId !== p.type ? (
        <p className="app-small">Save to change the type. Settings the new type doesn&apos;t use are cleared.</p>
      ) : (
        <>
          <div className="field">
            <label className="field-label" htmlFor="pf-label">Label</label>
            <input id="pf-label" className="input" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} />
          </div>

          <fieldset className={styles.group}>
            <legend className="field-label">Status</legend>
            <div className={styles.chips}>
              <button type="button" className="chip" aria-pressed={status === "proposed"} onClick={() => setStatus("proposed")}>Proposed</button>
              <button type="button" className="chip" aria-pressed={status === "existing"} onClick={() => setStatus("existing")}>Existing</button>
            </div>
          </fieldset>

          {status === "proposed" && (
            <fieldset className={styles.group}>
              <legend className="field-label">Build phase</legend>
              <div className={styles.chips}>
                {([1, 2, 3] as const).map((n) => (
                  <button key={n} type="button" className="chip" aria-pressed={phase === n} onClick={() => setPhase(n)}>{n}</button>
                ))}
              </div>
            </fieldset>
          )}

          {fields.has("species") && (
            <>
              <SpeciesPicker value={species} onChange={setSpecies} />
              <div className={styles.settings}>
                {type.geometry === "polygon" && (
                  <div className="field">
                    <label className="field-label" htmlFor="pf-row">Row spacing (ft)</label>
                    <input id="pf-row" className="input" inputMode="decimal" value={rowFt} onChange={(e) => setRowFt(e.target.value)} />
                  </div>
                )}
                {type.geometry !== "point" && (
                  <div className="field">
                    <label className="field-label" htmlFor="pf-plant">Plant spacing (ft)</label>
                    <input id="pf-plant" className="input" inputMode="decimal" value={plantFt} onChange={(e) => setPlantFt(e.target.value)} />
                  </div>
                )}
                {type.geometry === "line" && (
                  <div className="field">
                    <label className="field-label" htmlFor="pf-rows">Rows</label>
                    <input id="pf-rows" className="input" inputMode="numeric" value={rows} onChange={(e) => setRows(e.target.value)} />
                  </div>
                )}
                <div className="field">
                  <label className="field-label" htmlFor="pf-h">Mature height (ft)</label>
                  <input id="pf-h" className="input" inputMode="decimal" value={heightFt} onChange={(e) => setHeightFt(e.target.value)} />
                </div>
              </div>
            </>
          )}

          {fields.has("building") && (
            <>
              <div className="field">
                <label className="field-label" htmlFor="pf-bh">Height (ft)</label>
                <input id="pf-bh" className="input" inputMode="decimal" value={heightFt} onChange={(e) => setHeightFt(e.target.value)} />
              </div>
              <fieldset className={styles.group}>
                <legend className="field-label">Roof</legend>
                <div className={styles.chips}>
                  {library.roofs.map((r) => (
                    <button key={r} type="button" className="chip" aria-pressed={roof === r} onClick={() => setRoof(r)}>{ROOF_LABEL[r]}</button>
                  ))}
                </div>
              </fieldset>
            </>
          )}

          {fields.has("capacity") && (
            <div className="field">
              <label className="field-label" htmlFor="pf-cap">Capacity (gallons)</label>
              <input id="pf-cap" className="input" inputMode="numeric" value={gallons} onChange={(e) => setGallons(e.target.value)} />
            </div>
          )}

          <div className="field">
            <label className="field-label" htmlFor="pf-notes">Notes</label>
            <textarea id="pf-notes" className={`input ${styles.notes}`} rows={3} maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </>
      )}

      {error && <p className="error-text" role="alert">{error}</p>}
      <div className={styles.actions}>
        <button type="button" className="btn btn-sm btn-primary" onClick={save} disabled={saving}>{saving ? "Saving." : "Save"}</button>
        <button type="button" className="btn btn-sm" onClick={onEditShape} disabled={editingShape}><IconPencil size={14} /> Edit shape</button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onDelete}>Delete</button>
      </div>
    </section>
  );
}

/** Search USDA PLANTS by common or scientific name and build a species list. */
function SpeciesPicker({ value, onChange }: { value: SpeciesRef[]; onChange: (v: SpeciesRef[]) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Species[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      setLoading(true);
      api.searchSpecies(term)
        .then((r) => { if (live) { setResults(r); setError(null); } })
        .catch((e: Error) => { if (live) setError(e.message); })
        .finally(() => { if (live) setLoading(false); });
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q]);

  const add = (s: Species) => {
    if (!value.some((v) => v.symbol === s.symbol)) {
      onChange([...value, { symbol: s.symbol, scientific_name: s.scientific_name, common_name: s.common_name }]);
    }
    setQ("");
    setResults([]);
  };

  return (
    <div className={styles.species}>
      <label className="field-label" htmlFor="pf-species">Species</label>
      {value.length > 0 && (
        <ul className={styles.speciesList}>
          {value.map((s) => (
            <li key={s.symbol} className={styles.speciesItem}>
              <span>
                <span className={styles.itemTitle}>{s.common_name ? capitalize(s.common_name) : s.scientific_name}</span>
                {s.common_name && <span className={`app-small ${styles.sci}`}>{s.scientific_name}</span>}
              </span>
              <button type="button" className="icon-btn" aria-label={`Remove ${s.common_name ?? s.scientific_name}`}
                onClick={() => onChange(value.filter((v) => v.symbol !== s.symbol))}>
                <IconX size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <input id="pf-species" className="input" placeholder="apple, Quercus agrifolia" value={q} onChange={(e) => setQ(e.target.value)}
        autoComplete="off" aria-describedby="pf-species-help" />
      <p className="app-small" id="pf-species-help">From USDA PLANTS. Trait data is fuller for some species than others.</p>
      {loading && <p className="app-small">Searching.</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      {results.length > 0 && (
        <ul className={styles.results} aria-label="Matching species">
          {results.map((s) => (
            <li key={s.symbol}>
              <button type="button" className={styles.resultBtn} onClick={() => add(s)}>
                <span className={styles.itemTitle}>{s.common_name ? capitalize(s.common_name) : s.scientific_name}</span>
                <span className="app-small">{s.scientific_name}{s.traits.height_ft_mature ? ` · ${s.traits.height_ft_mature} ft` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!loading && q.trim().length >= 2 && results.length === 0 && !error && <p className="app-small">No matches.</p>}
    </div>
  );
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
