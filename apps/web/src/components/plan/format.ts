// Display formats for master plan measurements (the API is metric; US units on screen).
import { m2ToAcres, m2ToFt2, mToFt } from "@/lib/units";

const int = (n: number) => Math.round(n).toLocaleString("en-US");

/** Acres from half an acre up, square feet below. */
export function formatArea(m2: number): string {
  const ac = m2ToAcres(m2);
  return ac >= 0.5 ? `${ac.toFixed(ac >= 10 ? 0 : 1)} ac` : `${int(m2ToFt2(m2))} sq ft`;
}

export function formatLength(m: number): string {
  return `${int(mToFt(m))} ft`;
}

/** A metric setting shown in feet, to one decimal where it matters. */
export function feetValue(m: number | null | undefined): string {
  if (m == null) return "";
  const ft = mToFt(m);
  return String(Math.round(ft * 10) / 10);
}
