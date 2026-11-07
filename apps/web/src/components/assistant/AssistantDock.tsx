"use client";
// The assistant on every project step: a header button, a side panel, and at most one nudge at a time.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type AssistantStep, type ChatMessage, type Proposal } from "@/lib/api";
import { useAssistant } from "@/lib/assistant";
import { formatFeet, m2ToAcres } from "@/lib/units";
import { IconAlert, IconArrowRight, IconCheck, IconX } from "../Icons";
import styles from "./AssistantDock.module.css";

const STEP_LABEL: Record<AssistantStep, string> = {
  site: "Site", survey: "Survey", terrain: "Terrain", design: "Design", estimate: "Estimate",
};

const STARTERS: Record<AssistantStep, string[]> = {
  site: ["What makes a good site boundary?", "What will this app produce for my land?"],
  survey: ["Is my data good enough for keyline design?", "What does DEM resolution mean?", "What should I do next?"],
  terrain: ["What do these keypoints mean?", "Which keypoints should I confirm?", "Where does water leave my site?"],
  design: [
    "What should I know about this site before laying keylines?",
    "Propose two keyline options for the main valley.",
    "Where would a swale help most, and how much would it hold?",
  ],
  estimate: ["What drives the total?", "What isn't included in this estimate?"],
};

const INTRO: Record<AssistantStep, string> = {
  site: "Ask about boundaries, the steps ahead, or what the app can do.",
  survey: "Ask about elevation data, data quality, or building the terrain model.",
  terrain: "Ask what the map and numbers mean, or which keypoints to trust.",
  design:
    "Ask about the site, the rules, or plants, or ask for layout options. Every line it proposes is computed from the terrain model and stays a draft until you accept it.",
  estimate: "Ask what drives the cost, what's included, or how to adjust unit costs.",
};

interface Nudge { key: string; text: string; prompt: string }

/** One nudge at a decision point, from what the page reports. Each shows once per project until dismissed. */
function nudgeFor(step: AssistantStep | null, ctx: Record<string, unknown>): Nudge | null {
  const n = (k: string) => (typeof ctx[k] === "number" ? (ctx[k] as number) : null);
  if (step === "terrain" && (n("keypoint_count") ?? 0) > 0 && n("keypoints_confirmed") === 0) {
    const count = n("keypoint_count");
    return {
      key: "terrain-unconfirmed",
      text: `None of the ${count} keypoints are confirmed yet. Want a quick walkthrough of how to judge them?`,
      prompt: "Walk me through how to judge these keypoints and which ones to confirm.",
    };
  }
  if (step === "survey" && (n("coarse_pct") ?? 0) >= 50) {
    return {
      key: "survey-coarse",
      text: "This data is too coarse for keylines. Want to know what it would take to reach design grade?",
      prompt: "My data is too coarse for keylines. What would it take to get design-grade data?",
    };
  }
  if (step === "estimate" && n("line_item_count") === 0) {
    return {
      key: "estimate-empty",
      text: "Nothing to estimate yet. Want help deciding what to lay out first?",
      prompt: "There's nothing in the estimate yet. What should I lay out first?",
    };
  }
  return null;
}

const num = (v: unknown, d = 0) => (typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: d }) : "—");

function ProposalCard({ p, previewing, onPreview, onAccept, onDiscard, busy, canAct, projectId }: {
  p: Proposal;
  previewing: boolean;
  onPreview: () => void;
  onAccept: () => void;
  onDiscard: () => void;
  busy: boolean;
  canAct: boolean;
  projectId: string;
}) {
  const s = p.summary as Record<string, number | string | null | string[]>;
  const facts: [string, string][] =
    p.kind === "keyline"
      ? [
          ["Keypoint", String(s.keypoint_id ?? "—")],
          ["Keyline", `${formatFeet(s.keyline_length_m as number)} ft`],
          ["Rip lines", num(s.rip_count)],
          ["Area treated", `${m2ToAcres((s.area_treated_m2 as number) ?? 0).toFixed(1)} ac`],
          ["Pattern", `${p.params.pattern}, 1:${Math.round(1 / Number(p.params.grade || 1 / 300))}`],
        ]
      : [
          ["Near", `${s.keypoint_id}${s.rise_m ? ` ${Number(s.rise_m) > 0 ? "+" : ""}${formatFeet(s.rise_m as number)} ft` : ""}`],
          ["Length", `${formatFeet(s.length_m as number)} ft`],
          ["Storage", `${num(s.storage_gal)} gal`],
          ["Catchment", `${m2ToAcres((s.catchment_m2 as number) ?? 0).toFixed(1)} ac`],
        ];
  return (
    <div className={`${styles.proposal} ${previewing ? styles.previewing : ""}`}>
      <div className={styles.propHead}>
        <span className={styles.propTitle}>{p.kind === "keyline" ? "Keyline pattern" : "Swale"} · draft</span>
        {canAct && (
          <button type="button" className="chip" aria-pressed={previewing} onClick={onPreview}>
            {previewing ? "Hide" : "Preview"}
          </button>
        )}
      </div>
      <dl className={styles.facts}>
        {facts.map(([k, v]) => (
          <div key={k}><dt className="app-small">{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {(s.notes as string[] | undefined)?.slice(0, 3).map((n) => (
        <p key={n} className={`app-small ${styles.note}`}><IconAlert size={12} /> {n}</p>
      ))}
      {p.status !== "draft" ? (
        <p className="app-small">{p.status === "accepted" ? "Added to the design." : "Discarded."}</p>
      ) : canAct ? (
        <div className={styles.propActions}>
          <button type="button" className="btn btn-sm btn-primary" onClick={onAccept} disabled={busy}>
            <IconCheck size={14} /> Accept
          </button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onDiscard} disabled={busy}>
            <IconX size={14} /> Discard
          </button>
        </div>
      ) : (
        <p className="app-small">
          Draft. <Link href={`/projects/${projectId}/design`}>Open the Design step</Link> to preview or accept it.
        </p>
      )}
    </div>
  );
}

/** The header button. Shows a dot while a nudge is waiting. */
export function AssistantButton() {
  const { projectId, step, open, setOpen, pageContext, dismissedNudges } = useAssistant();
  if (!projectId || !step) return null;
  const nudge = nudgeFor(step, pageContext);
  const waiting = !!nudge && !dismissedNudges.includes(nudge.key) && !open;
  return (
    <button
      type="button"
      className={`${styles.headerBtn} ${open ? styles.headerBtnOn : ""}`}
      aria-pressed={open}
      aria-controls="assistant-panel"
      onClick={() => setOpen(!open)}
    >
      Assistant
      {waiting && <span className={styles.dot} aria-label="A suggestion is waiting" />}
    </button>
  );
}

export function AssistantDock() {
  const {
    projectId, step, pageContext, design, open, setOpen, turns, setTurns, proposals, setProposals,
    dismissedNudges: dismissed, dismissNudge: dismiss,
  } = useAssistant();
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, thinking, open]);

  // A preview belongs to the Design page's map; drop it when that page goes away.
  useEffect(() => {
    if (!design) setPreviewId(null);
  }, [design]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!projectId || !step) return null;

  const nudge = nudgeFor(step, pageContext);
  const showNudge = !!nudge && !dismissed.includes(nudge.key) && !open;

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || thinking) return;
    // Send recent turns only, starting from a person's message.
    const history: ChatMessage[] = [...turns.map(({ role, content }) => ({ role, content })), { role: "user", content }];
    let recent = history.slice(-20);
    while (recent.length && recent[0].role !== "user") recent = recent.slice(1);
    setTurns((t) => [...t, { role: "user", content }]);
    setDraft("");
    setThinking(true);
    setError(null);
    try {
      const r = await api.askAssistant(projectId, recent, design?.allowPlanning ?? false, step, pageContext);
      setProposals((m) => ({ ...m, ...Object.fromEntries(r.proposals.map((p) => [p.id, p])) }));
      setTurns((t) => [...t, { role: "assistant", content: r.reply, reply: r }]);
      if (r.proposals[0] && design) {
        setPreviewId(r.proposals[0].id);
        design.onPreview(r.proposals[0]);
      }
    } catch (e) {
      setError((e as Error).message);
      setTurns((t) => t.slice(0, -1));
      setDraft(content);
    } finally {
      setThinking(false);
    }
  };

  const takeNudge = (n: Nudge) => {
    dismiss(n.key);
    setOpen(true);
    send(n.prompt);
  };

  const togglePreview = (p: Proposal) => {
    if (!design) return;
    const next = previewId === p.id ? null : p.id;
    setPreviewId(next);
    design.onPreview(next ? p : null);
  };

  const accept = async (p: Proposal) => {
    setBusy(p.id);
    setError(null);
    try {
      const updated = await api.acceptProposal(projectId, p.id);
      setProposals((m) => ({ ...m, [p.id]: updated }));
      if (previewId === p.id) {
        setPreviewId(null);
        design?.onPreview(null);
      }
      design?.onDesignChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const discard = async (p: Proposal) => {
    setBusy(p.id);
    try {
      await api.discardProposal(projectId, p.id);
      setProposals((m) => ({ ...m, [p.id]: { ...p, status: "discarded" } }));
      if (previewId === p.id) {
        setPreviewId(null);
        design?.onPreview(null);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const clear = () => {
    setTurns([]);
    setProposals({});
    setPreviewId(null);
    design?.onPreview(null);
    setError(null);
  };

  return (
    <>
      {showNudge && nudge && (
        <div className={styles.nudge} role="status">
          <p className={styles.nudgeText}>{nudge.text}</p>
          <div className={styles.nudgeActions}>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => takeNudge(nudge)}>
              Walk me through it
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => dismiss(nudge.key)}>
              Not now
            </button>
          </div>
        </div>
      )}
      <aside id="assistant-panel" className={styles.panel} hidden={!open} aria-labelledby="assistant-title">
        <div className={styles.head}>
          <p className="app-eyebrow" id="assistant-title">Assistant · {STEP_LABEL[step]}</p>
          <div className={styles.headActions}>
            {turns.length > 0 && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={clear}>New chat</button>
            )}
            <button type="button" className={styles.close} onClick={() => setOpen(false)} aria-label="Close the assistant">
              <IconX size={16} />
            </button>
          </div>
        </div>
        <div className={styles.log} aria-live="polite">
          {turns.length === 0 && (
            <div className={styles.starters}>
              <p className="app-small">{INTRO[step]}</p>
              {STARTERS[step].map((s) => (
                <button key={s} type="button" className={styles.starter} onClick={() => send(s)}>
                  {s} <IconArrowRight size={14} />
                </button>
              ))}
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={t.role === "user" ? styles.user : styles.bot}>
              {t.content.split(/\n{2,}/).map((para, j) => (
                <p key={j} className={styles.para}>{para}</p>
              ))}
              {t.reply?.proposals.map((p) => (
                <ProposalCard key={p.id} p={proposals[p.id] ?? p} previewing={previewId === p.id} busy={busy === p.id}
                  canAct={!!design} projectId={projectId}
                  onPreview={() => togglePreview(proposals[p.id] ?? p)} onAccept={() => accept(p)} onDiscard={() => discard(p)} />
              ))}
              {t.reply && t.reply.citations.length > 0 && (
                <ul className={styles.cites} aria-label="Sources">
                  {t.reply.citations.map((c) => (
                    <li key={c.title}>{c.url && /^https:\/\//.test(c.url) ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {thinking && <div className="progress progress-indeterminate" aria-label="Assistant is working"><span /></div>}
          <div ref={endRef} />
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        {turns.length > 0 && !thinking && (
          <div className={styles.more}>
            {STARTERS[step].filter((s) => !turns.some((t) => t.content === s)).slice(0, 2).map((s) => (
              <button key={s} type="button" className="chip" onClick={() => send(s)}>{s}</button>
            ))}
          </div>
        )}
        <form className={styles.form} onSubmit={(e) => { e.preventDefault(); send(draft); }}>
          <textarea
            ref={inputRef}
            className={`input ${styles.input}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            placeholder={`Ask about the ${STEP_LABEL[step]} step`}
            rows={2}
            aria-label="Message the assistant"
          />
          <button type="submit" className="btn btn-sm btn-primary" disabled={thinking || !draft.trim()}>
            {thinking ? "Working." : "Send"}
          </button>
        </form>
      </aside>
    </>
  );
}
