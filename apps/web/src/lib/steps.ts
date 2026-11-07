// The project steps shown across the top of every project page. One list, so the header, page eyebrows and the
// assistant agree. Export is reached from the Estimate step and counts as Estimate.
import type { AssistantStep } from "./api";

export const STEPS: { seg: AssistantStep; label: string }[] = [
  { seg: "site", label: "Site" },
  { seg: "goals", label: "Goals" },
  { seg: "survey", label: "Survey" },
  { seg: "terrain", label: "Terrain" },
  { seg: "ideas", label: "Ideas" },
  { seg: "design", label: "Design" },
  { seg: "estimate", label: "Estimate" },
];

/** Matches /projects/{id}/{step}; group 1 is the id, group 2 the segment (export included). */
export const STEP_PATH = /^\/projects\/([^/]+)\/(site|goals|survey|terrain|ideas|design|estimate|export)/;

export function stepOf(seg: string | undefined | null): AssistantStep | null {
  if (!seg) return null;
  if (seg === "export") return "estimate";
  return STEPS.some((s) => s.seg === seg) ? (seg as AssistantStep) : null;
}

/** "Step 3 of 7" */
export function stepCount(seg: AssistantStep): string {
  return `Step ${STEPS.findIndex((s) => s.seg === seg) + 1} of ${STEPS.length}`;
}

/** Broadcast that the goals brief or the plan changed, so mounted pages reload (for example after the assistant's
 *  suggestion is applied from the side panel). */
export type ProjectChange = "brief" | "plan";
export const PROJECT_CHANGED = "tr:project-changed";

export function announceChange(what: ProjectChange) {
  window.dispatchEvent(new CustomEvent<ProjectChange>(PROJECT_CHANGED, { detail: what }));
}
