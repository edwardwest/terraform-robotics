"use client";
// The assistant's shared state: one conversation per project that follows the person across steps,
// plus what the current page reports about itself (page context) and, on the Design step, the hooks
// that let proposals preview on the map.
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { AssistantReply, AssistantStep, ChatMessage, Proposal } from "./api";

export type Turn = ChatMessage & { reply?: AssistantReply };

export interface DesignHooks {
  allowPlanning: boolean;
  onPreview: (p: Proposal | null) => void;
  onDesignChanged: () => void;
}

interface AssistantState {
  projectId: string | null;
  step: AssistantStep | null;
  pageContext: Record<string, unknown>;
  setPageContext: (step: AssistantStep, ctx: Record<string, unknown> | null) => void;
  design: DesignHooks | null;
  setDesign: (h: DesignHooks | null) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
  turns: Turn[];
  setTurns: React.Dispatch<React.SetStateAction<Turn[]>>;
  proposals: Record<string, Proposal>;
  setProposals: React.Dispatch<React.SetStateAction<Record<string, Proposal>>>;
  dismissedNudges: string[];
  dismissNudge: (key: string) => void;
}

const Ctx = createContext<AssistantState | null>(null);

const STEP_PATH = /^\/projects\/([^/]+)\/(site|survey|terrain|design|estimate|export)/;
const MAX_KEPT_TURNS = 40;

function read<T>(storage: () => Storage, key: string, fallback: T): T {
  try {
    const raw = storage().getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(storage: () => Storage, key: string, value: unknown) {
  try {
    storage().setItem(key, JSON.stringify(value));
  } catch {
    /* storage can be full or blocked; the conversation still works in memory */
  }
}

const session = () => window.sessionStorage;
const local = () => window.localStorage;

export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "/";
  const m = path.match(STEP_PATH);
  const projectId = m && m[1] !== "new" ? m[1] : null;
  const step: AssistantStep | null = !m ? null : m[2] === "export" ? "estimate" : (m[2] as AssistantStep);

  const [contexts, setContexts] = useState<Partial<Record<AssistantStep, Record<string, unknown>>>>({});
  const [design, setDesign] = useState<DesignHooks | null>(null);
  const [open, setOpenState] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [proposals, setProposals] = useState<Record<string, Proposal>>({});
  const [dismissedNudges, setDismissed] = useState<string[]>([]);
  const loadedFor = useRef<string | null>(null);

  // Load this project's conversation (kept for the browser session) when the project changes.
  useEffect(() => {
    if (!projectId || loadedFor.current === projectId) return;
    loadedFor.current = projectId;
    setTurns(read<Turn[]>(session, `tr.assistant.${projectId}`, []));
    setProposals({});
    setContexts({});
    setOpenState(read<boolean>(local, "tr.assistant.open", false));
    setDismissed(read<string[]>(local, `tr.assistant.nudges.${projectId}`, []));
  }, [projectId]);

  const dismissNudge = useCallback((key: string) => {
    setDismissed((l) => {
      const next = l.includes(key) ? l : [...l, key];
      if (projectId) write(local, `tr.assistant.nudges.${projectId}`, next);
      return next;
    });
  }, [projectId]);

  useEffect(() => {
    if (projectId && loadedFor.current === projectId) write(session, `tr.assistant.${projectId}`, turns.slice(-MAX_KEPT_TURNS));
  }, [projectId, turns]);

  // While open on a wide screen the panel takes room from the page rather than covering it.
  useEffect(() => {
    const on = open && !!projectId;
    document.body.dataset.assistant = on ? "open" : "closed";
    const t = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 60); // maps re-measure
    return () => window.clearTimeout(t);
  }, [open, projectId]);

  const setOpen = useCallback((v: boolean) => {
    setOpenState(v);
    write(local, "tr.assistant.open", v);
  }, []);

  const setPageContext = useCallback((s: AssistantStep, ctx: Record<string, unknown> | null) => {
    setContexts((c) => {
      if (ctx === null) {
        const next = { ...c };
        delete next[s];
        return next;
      }
      return { ...c, [s]: ctx };
    });
  }, []);

  const value = useMemo<AssistantState>(
    () => ({
      projectId, step, pageContext: (step && contexts[step]) || {}, setPageContext, design, setDesign,
      open, setOpen, turns, setTurns, proposals, setProposals, dismissedNudges, dismissNudge,
    }),
    [projectId, step, contexts, setPageContext, design, open, setOpen, turns, proposals, dismissedNudges, dismissNudge],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAssistant(): AssistantState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAssistant must be used inside AssistantProvider");
  return v;
}

/** A step page reports what is on screen. Keep it small: facts, ids and counts, metric units. */
export function useAssistantPage(step: AssistantStep, ctx: Record<string, unknown>) {
  const { setPageContext } = useAssistant();
  const key = JSON.stringify(ctx);
  useEffect(() => {
    setPageContext(step, JSON.parse(key));
  }, [step, key, setPageContext]);
  useEffect(() => () => setPageContext(step, null), [step, setPageContext]);
}

/** The Design page lends the assistant its map preview and refresh while it is mounted. */
export function useAssistantDesign(hooks: DesignHooks | null) {
  const { setDesign } = useAssistant();
  const latest = useRef(hooks);
  latest.current = hooks;
  const allowPlanning = hooks?.allowPlanning ?? false;
  const present = hooks !== null;
  useEffect(() => {
    if (!present) {
      setDesign(null);
      return;
    }
    setDesign({
      allowPlanning,
      onPreview: (p) => latest.current?.onPreview(p),
      onDesignChanged: () => latest.current?.onDesignChanged(),
    });
  }, [present, allowPlanning, setDesign]);
  useEffect(() => () => setDesign(null), [setDesign]);
}
