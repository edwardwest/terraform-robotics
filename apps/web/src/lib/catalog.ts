"use client";
// The intervention catalog (goals, answer options, phases, categories, interventions) changes only with a deploy,
// so it is fetched once per page load and shared.
import { useEffect, useState } from "react";
import { api, type BriefUpdate, type Catalog, type QuantityBasis } from "./api";
import { M2_PER_ACRE, acresToM2, ft2ToM2, ftToM, galToM3, m2ToAcres, m2ToFt2, m3ToGal, mToFt, mmToIn } from "./units";

let cached: Promise<Catalog> | null = null;

export function loadCatalog(): Promise<Catalog> {
  if (!cached) {
    cached = api.getCatalog().catch((e) => {
      cached = null;
      throw e;
    });
  }
  return cached;
}

export function useCatalog(): { catalog: Catalog | null; error: string | null } {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    loadCatalog().then((c) => live && setCatalog(c)).catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, []);
  return { catalog, error };
}

export function optionLabel(catalog: Catalog | null, kind: "goals" | "phases" | "categories", id: string): string;
export function optionLabel(catalog: Catalog | null, kind: keyof Catalog["questions"], id: string): string;
export function optionLabel(catalog: Catalog | null, kind: string, id: string): string {
  if (!catalog) return id;
  const list =
    kind === "goals" ? catalog.goals : kind === "phases" ? catalog.phases : kind === "categories" ? catalog.categories
      : catalog.questions[kind as keyof Catalog["questions"]];
  return list?.find((o) => o.id === id)?.label ?? id;
}

/** Short human lines for a (partial) brief, in the catalog's words. Used for the assistant's suggestion card. */
export function describeBrief(catalog: Catalog | null, b: BriefUpdate): [string, string][] {
  const rows: [string, string][] = [];
  if (b.goals?.length) rows.push(["Goals", b.goals.map((g, i) => `${i + 1}. ${optionLabel(catalog, "goals", g)}`).join("  ")]);
  if (b.setting) rows.push(["Land use", optionLabel(catalog, "setting", b.setting)]);
  if (b.has_buildings != null) rows.push(["Buildings on site", b.has_buildings ? "Yes" : "No"]);
  if (b.water_sources?.length) rows.push(["Water", b.water_sources.map((w) => optionLabel(catalog, "water_sources", w)).join(", ")]);
  if (b.annual_rainfall_mm != null) rows.push(["Annual rainfall", `${Math.round(mmToIn(b.annual_rainfall_mm))} in`]);
  if (b.budget) rows.push(["Budget", optionLabel(catalog, "budget", b.budget)]);
  if (b.timeline) rows.push(["Timeline", optionLabel(catalog, "timeline", b.timeline)]);
  if (b.maintenance) rows.push(["Upkeep", optionLabel(catalog, "maintenance", b.maintenance)]);
  if (b.constraints?.length) rows.push(["Constraints", b.constraints.map((c) => optionLabel(catalog, "constraints", c)).join(", ")]);
  if (b.vision) rows.push(["Vision", b.vision]);
  return rows;
}

/** Display unit for a plan quantity basis. Areas under half an acre show in square feet. */
export function quantityUnit(basis: QuantityBasis, metric: number | null): { unit: string; toDisplay: (m: number) => number; toMetric: (d: number) => number } {
  switch (basis) {
    case "area_m2":
      return (metric ?? 0) >= M2_PER_ACRE / 2
        ? { unit: "acres", toDisplay: m2ToAcres, toMetric: acresToM2 }
        : { unit: "sq ft", toDisplay: m2ToFt2, toMetric: ft2ToM2 };
    case "length_m":
      return { unit: "ft", toDisplay: mToFt, toMetric: ftToM };
    case "volume_m3":
      return { unit: "gallons", toDisplay: m3ToGal, toMetric: galToM3 };
    default:
      return { unit: "", toDisplay: (m) => m, toMetric: (d) => d };
  }
}

export function formatQuantity(basis: QuantityBasis | null, metric: number | null): string {
  if (!basis || metric == null) return "";
  const u = quantityUnit(basis, metric);
  const d = u.toDisplay(metric);
  const digits = u.unit === "acres" && d < 10 ? 1 : 0;
  const n = d.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
  return u.unit ? `${n} ${u.unit}` : n;
}

export const tierLabel = (t: number) => "$".repeat(Math.max(1, Math.min(4, t)));
