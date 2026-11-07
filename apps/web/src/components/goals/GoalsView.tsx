"use client";
// Step 2: the goals brief. What the person wants from the land, so the Ideas step can rank interventions to fit.
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type Brief, type BriefUpdate, type Project, type QuestionKey } from "@/lib/api";
import { INTERVIEW_PROMPT, useAssistant, useAssistantPage } from "@/lib/assistant";
import { optionLabel, useCatalog } from "@/lib/catalog";
import { PROJECT_CHANGED, stepCount, type ProjectChange } from "@/lib/steps";
import { formatAcres, inToMm, mmToIn } from "@/lib/units";
import { IconArrowRight } from "../Icons";
import styles from "./GoalsView.module.css";

const MAX_GOALS = 5;
type Form = Required<{ [K in keyof BriefUpdate]: BriefUpdate[K] }>;

const EMPTY: Form = {
  goals: [], setting: null, has_buildings: null, water_sources: [], annual_rainfall_mm: null, budget: null,
  timeline: null, maintenance: null, constraints: [], vision: null,
};

function toForm(b: Brief): Form {
  return {
    goals: b.goals ?? [], setting: b.setting ?? null, has_buildings: b.has_buildings ?? null,
    water_sources: b.water_sources ?? [], annual_rainfall_mm: b.annual_rainfall_mm ?? null, budget: b.budget ?? null,
    timeline: b.timeline ?? null, maintenance: b.maintenance ?? null, constraints: b.constraints ?? [],
    vision: b.vision ?? null,
  };
}

export function GoalsView({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { catalog, error: catalogError } = useCatalog();
  const { ask } = useAssistant();
  const [project, setProject] = useState<Project | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [rainIn, setRainIn] = useState("");
  const [saved, setSaved] = useState<Form | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const b = await api.getBrief(projectId);
      const f = toForm(b);
      setForm(f);
      setSaved(f);
      setSavedAt(b.updated_at);
      setRainIn(f.annual_rainfall_mm != null ? String(Math.round(mmToIn(f.annual_rainfall_mm))) : "");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setError(e.message));
    load();
  }, [projectId, load]);

  // The assistant's suggestions are applied from the side panel; reload when that happens.
  useEffect(() => {
    const on = (e: Event) => {
      if ((e as CustomEvent<ProjectChange>).detail === "brief") load();
    };
    window.addEventListener(PROJECT_CHANGED, on);
    return () => window.removeEventListener(PROJECT_CHANGED, on);
  }, [load]);

  const dirty = saved !== null && JSON.stringify(form) !== JSON.stringify(saved);

  useAssistantPage("goals", {
    page: "Goals",
    goal_count: saved ? (saved.goals?.length ?? 0) : null,
    saved_brief: saved,
    unsaved_changes: dirty,
  });

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  const toggleGoal = (id: string) =>
    setForm((f) => {
      const g = f.goals ?? [];
      if (g.includes(id)) return { ...f, goals: g.filter((x) => x !== id) };
      return g.length >= MAX_GOALS ? f : { ...f, goals: [...g, id] };
    });

  const toggleIn = (k: "water_sources" | "constraints", id: string) =>
    setForm((f) => {
      const list = f[k] ?? [];
      return { ...f, [k]: list.includes(id) ? list.filter((x) => x !== id) : [...list, id] };
    });

  const save = async (): Promise<boolean> => {
    setSaving(true);
    setError(null);
    try {
      const rain = parseFloat(rainIn);
      const body: BriefUpdate = {
        ...form,
        annual_rainfall_mm: Number.isFinite(rain) && rain > 0 ? Math.round(inToMm(rain)) : null,
        vision: form.vision?.trim() || null,
      };
      const b = await api.saveBrief(projectId, body);
      const f = toForm(b);
      setForm(f);
      setSaved(f);
      setSavedAt(b.updated_at);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  };

  const go = async (seg: "survey" | "ideas") => {
    if (dirty && !(await save())) return;
    router.push(`/projects/${projectId}/${seg}`);
  };

  const chosen = form.goals ?? [];

  const choice = (q: QuestionKey, value: string | null, onPick: (v: string | null) => void) => (
    <div className={styles.chips} role="radiogroup">
      {catalog?.questions[q].map((o) => (
        <button key={o.id} type="button" className="chip" role="radio" aria-checked={value === o.id}
          aria-pressed={value === o.id} onClick={() => onPick(value === o.id ? null : o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );

  const multi = (q: "water_sources" | "constraints", values: string[]) => (
    <div className={styles.chips}>
      {catalog?.questions[q].map((o) => (
        <button key={o.id} type="button" className="chip" aria-pressed={values.includes(o.id)} onClick={() => toggleIn(q, o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className={styles.layout}>
      <header className={styles.head}>
        <p className="app-eyebrow">
          {project ? `${project.name} · ${formatAcres(project.area_m2)} acres · ` : ""}{stepCount("goals")}
        </p>
        <h1 className="app-display">What do you want from this land?</h1>
        <p className="app-body">
          Your goals decide which interventions the Ideas step suggests and in what order. Pick what matters, or talk it
          through with the assistant and apply what it hears.
        </p>
        <div className={styles.headActions}>
          <button type="button" className="btn" onClick={() => ask(INTERVIEW_PROMPT)}>
            Talk it through with the assistant
          </button>
        </div>
      </header>

      {(error || catalogError) && <p className="error-text" role="alert">{error || catalogError}</p>}

      <section className={`card ${styles.section}`} aria-labelledby="goals-h">
        <div>
          <p className="app-eyebrow" id="goals-h">Goals</p>
          <p className="app-small">
            Pick up to {MAX_GOALS}, most important first. The number shows each goal&apos;s priority; click a goal again to
            remove it.
          </p>
        </div>
        <div className={styles.goalGrid}>
          {catalog?.goals.map((g) => {
            const rank = chosen.indexOf(g.id);
            const on = rank >= 0;
            return (
              <button key={g.id} type="button" className={`${styles.goal} ${on ? styles.goalOn : ""}`} aria-pressed={on}
                disabled={!on && chosen.length >= MAX_GOALS} onClick={() => toggleGoal(g.id)}>
                <span className={styles.goalTop}>
                  <span className={styles.goalLabel}>{g.label}</span>
                  {on && <span className={styles.rank} aria-label={`priority ${rank + 1}`}>{rank + 1}</span>}
                </span>
                <span className="app-small">{g.hint}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className={`card ${styles.section}`} aria-labelledby="land-h">
        <p className="app-eyebrow" id="land-h">The land</p>
        <fieldset className={styles.group}>
          <legend className="field-label">How the land is used</legend>
          {choice("setting", form.setting, (v) => set("setting", v))}
        </fieldset>
        <fieldset className={styles.group}>
          <legend className="field-label">Buildings on site</legend>
          <div className={styles.chips} role="radiogroup">
            {([true, false] as const).map((v) => (
              <button key={String(v)} type="button" className="chip" role="radio" aria-checked={form.has_buildings === v}
                aria-pressed={form.has_buildings === v} onClick={() => set("has_buildings", form.has_buildings === v ? null : v)}>
                {v ? "Yes" : "No"}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className={styles.group}>
          <legend className="field-label">Water sources</legend>
          {multi("water_sources", form.water_sources ?? [])}
        </fieldset>
        <label className={`field ${styles.narrow}`}>
          <span className="field-label">Annual rainfall (in)</span>
          <input className="input" type="number" min={0} max={240} inputMode="decimal" value={rainIn}
            onChange={(e) => setRainIn(e.target.value)} placeholder="If you know it" />
        </label>
      </section>

      <section className={`card ${styles.section}`} aria-labelledby="effort-h">
        <p className="app-eyebrow" id="effort-h">Budget and effort</p>
        <fieldset className={styles.group}>
          <legend className="field-label">Budget</legend>
          {choice("budget", form.budget, (v) => set("budget", v))}
        </fieldset>
        <fieldset className={styles.group}>
          <legend className="field-label">Timeline</legend>
          {choice("timeline", form.timeline, (v) => set("timeline", v))}
        </fieldset>
        <fieldset className={styles.group}>
          <legend className="field-label">Upkeep you want</legend>
          {choice("maintenance", form.maintenance, (v) => set("maintenance", v))}
        </fieldset>
      </section>

      <section className={`card ${styles.section}`} aria-labelledby="limits-h">
        <p className="app-eyebrow" id="limits-h">Constraints</p>
        {multi("constraints", form.constraints ?? [])}
        <label className="field">
          <span className="field-label">Your vision</span>
          <textarea className={`input ${styles.vision}`} rows={3} maxLength={1500} value={form.vision ?? ""}
            onChange={(e) => set("vision", e.target.value)}
            placeholder="In a few sentences: what should this land be like in ten years?" />
        </label>
      </section>

      <footer className={styles.foot}>
        <button type="button" className="btn" onClick={save} disabled={saving || !dirty}>
          {saving ? "Saving." : "Save goals"}
        </button>
        <span className="app-small" aria-live="polite">
          {dirty ? "Unsaved changes." : savedAt ? "Saved." : chosen.length ? "" : "No goals yet."}
        </span>
        <span className={styles.spacer} />
        <button type="button" className="btn btn-ghost" onClick={() => go("ideas")} disabled={saving}>
          See ideas now
        </button>
        <button type="button" className="btn btn-primary" onClick={() => go("survey")} disabled={saving}>
          Continue to survey <IconArrowRight />
        </button>
      </footer>
      {catalog && chosen.length > 0 && (
        <p className={`app-small ${styles.summary}`}>
          Priorities: {chosen.map((g, i) => `${i + 1}. ${optionLabel(catalog, "goals", g)}`).join(" · ")}
        </p>
      )}
    </div>
  );
}
