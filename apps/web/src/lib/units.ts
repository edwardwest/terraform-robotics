// The API is metric. All conversions to US customary display units live here.

export const FT_PER_M = 3.280839895;
export const M2_PER_ACRE = 4046.8564224;
export const M_PER_MILE = 1609.344;

export const mToFt = (m: number): number => m * FT_PER_M;
export const ftToM = (ft: number): number => ft / FT_PER_M;
export const m2ToAcres = (m2: number): number => m2 / M2_PER_ACRE;
export const acresToM2 = (acres: number): number => acres * M2_PER_ACRE;
export const mToMiles = (m: number): number => m / M_PER_MILE;
export const m2ToFt2 = (m2: number): number => m2 * FT_PER_M * FT_PER_M;
export const ft2ToM2 = (ft2: number): number => ft2 / (FT_PER_M * FT_PER_M);
export const GAL_PER_M3 = 264.172052;
export const m3ToGal = (m3: number): number => m3 * GAL_PER_M3;
export const galToM3 = (gal: number): number => gal / GAL_PER_M3;
export const MM_PER_IN = 25.4;
export const mmToIn = (mm: number): number => mm / MM_PER_IN;
export const inToMm = (inches: number): number => inches * MM_PER_IN;

const fmt = (n: number, digits: number): string =>
  n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** "40.0" acres; fewer than 10 acres gets two decimals. */
export function formatAcres(m2: number | null | undefined): string {
  if (m2 == null || !Number.isFinite(m2)) return "—";
  const a = m2ToAcres(m2);
  return fmt(a, a < 10 ? 2 : 1);
}

export function formatMiles(m: number | null | undefined): string {
  if (m == null || !Number.isFinite(m)) return "—";
  return fmt(mToMiles(m), 2);
}

export function formatFeet(m: number | null | undefined, digits = 0): string {
  if (m == null || !Number.isFinite(m)) return "—";
  return fmt(mToFt(m), digits);
}

export function formatPct(p: number | null | undefined, digits = 0): string {
  if (p == null || !Number.isFinite(p)) return "—";
  return `${fmt(p, digits)}%`;
}

/** Resolution in metres to a short feet label, e.g. 0.5 m -> "1.6 ft". */
export function formatResolution(m: number | null | undefined): string {
  if (m == null || !Number.isFinite(m)) return "—";
  const ft = mToFt(m);
  return `${fmt(ft, ft < 10 ? 1 : 0)} ft`;
}

/** Pick a "nice" tick step (1, 2, 5 x 10^n) for an axis spanning `span` with about `target` ticks. */
export function niceStep(span: number, target = 5): number {
  if (!(span > 0)) return 1;
  const raw = span / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
  return step * mag;
}

export function ticks(min: number, max: number, target = 5): number[] {
  const step = niceStep(max - min, target);
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    out.push(Number(v.toFixed(10)));
  }
  return out;
}
