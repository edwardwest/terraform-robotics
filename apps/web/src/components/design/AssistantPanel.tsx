"use client";
import { useEffect, useRef, useState } from "react";
import { api, type AssistantReply, type ChatMessage, type Proposal } from "@/lib/api";
import { formatFeet, m2ToAcres } from "@/lib/units";
import { IconAlert, IconArrowRight, IconCheck, IconX } from "../Icons";
import styles from "./AssistantPanel.module.css";

const STARTERS = [
  "What should I know about this site before laying keylines?",
  "Propose two keyline options for the main valley.",
  "Where would a swale help most, and how much would it hold?",
];

const num = (v: unknown, d = 0) => (typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: d }) : "—");

function ProposalCard({ p, previewing, onPreview, onAccept, onDiscard, busy }: {
  p: Proposal;
  previewing: boolean;
  onPreview: () => void;
  onAccept: () => void;
  onDiscard: () => void;
  busy: boolean;
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
        <button type="button" className="chip" aria-pressed={previewing} onClick={onPreview}>
          {previewing ? "Hide" : "Preview"}
        </button>
      </div>
      <dl className={styles.facts}>
        {facts.map(([k, v]) => (
          <div key={k}><dt className="app-small">{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {(s.notes as string[] | undefined)?.slice(0, 3).map((n) => (
        <p key={n} className={`app-small ${styles.note}`}><IconAlert size={12} /> {n}</p>
      ))}
      {p.status === "draft" ? (
        <div className={styles.propActions}>
          <button type="button" className="btn btn-sm btn-primary" onClick={onAccept} disabled={busy}>
            <IconCheck size={14} /> Accept
          </button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onDiscard} disabled={busy}>
            <IconX size={14} /> Discard
          </button>
        </div>
      ) : (
        <p className="app-small">{p.status === "accepted" ? "Added to the design." : "Discarded."}</p>
      )}
    </div>
  );
}

export function AssistantPanel({ projectId, allowPlanning, onPreview, onDesignChanged }: {
  projectId: string;
  allowPlanning: boolean;
  onPreview: (p: Proposal | null) => void;
  onDesignChanged: () => void;
}) {
  type Turn = ChatMessage & { reply?: AssistantReply };
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Record<string, Proposal>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, thinking]);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || thinking) return;
    const history: ChatMessage[] = [...turns.map(({ role, content }) => ({ role, content })), { role: "user", content }];
    setTurns((t) => [...t, { role: "user", content }]);
    setDraft("");
    setThinking(true);
    setError(null);
    try {
      const r = await api.askAssistant(projectId, history, allowPlanning);
      setProposals((m) => ({ ...m, ...Object.fromEntries(r.proposals.map((p) => [p.id, p])) }));
      setTurns((t) => [...t, { role: "assistant", content: r.reply, reply: r }]);
      if (r.proposals[0]) {
        setPreviewId(r.proposals[0].id);
        onPreview(r.proposals[0]);
      }
    } catch (e) {
      setError((e as Error).message);
      setTurns((t) => t.slice(0, -1));
      setDraft(content);
    } finally {
      setThinking(false);
    }
  };

  const togglePreview = (p: Proposal) => {
    const next = previewId === p.id ? null : p.id;
    setPreviewId(next);
    onPreview(next ? p : null);
  };

  const accept = async (p: Proposal) => {
    setBusy(p.id);
    setError(null);
    try {
      const updated = await api.acceptProposal(projectId, p.id);
      setProposals((m) => ({ ...m, [p.id]: updated }));
      if (previewId === p.id) {
        setPreviewId(null);
        onPreview(null);
      }
      onDesignChanged();
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
        onPreview(null);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className={`card ${styles.panel}`} aria-labelledby="assistant-title">
      <p className="app-eyebrow" id="assistant-title">Design assistant</p>
      <div className={styles.log} aria-live="polite">
        {turns.length === 0 && (
          <div className={styles.starters}>
            <p className="app-small">Ask about the site, the rules, or plants, or ask for layout options. Every line it proposes is computed from the terrain model and stays a draft until you accept it.</p>
            {STARTERS.map((s) => (
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
                onPreview={() => togglePreview(proposals[p.id] ?? p)} onAccept={() => accept(p)} onDiscard={() => discard(p)} />
            ))}
            {t.reply && t.reply.citations.length > 0 && (
              <ul className={styles.cites} aria-label="Sources">
                {t.reply.citations.map((c) => (
                  <li key={c.title}>{c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {thinking && <div className="progress progress-indeterminate" aria-label="Assistant is working"><span /></div>}
        <div ref={endRef} />
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <form className={styles.form} onSubmit={(e) => { e.preventDefault(); send(draft); }}>
        <textarea
          className={`input ${styles.input}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
          placeholder="Ask the assistant"
          rows={2}
          aria-label="Message the design assistant"
        />
        <button type="submit" className="btn btn-sm btn-primary" disabled={thinking || !draft.trim()}>
          {thinking ? "Working." : "Send"}
        </button>
      </form>
    </section>
  );
}
