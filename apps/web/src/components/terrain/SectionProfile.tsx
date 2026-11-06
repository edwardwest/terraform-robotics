"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { Profile } from "@/lib/api";
import { mToFt, ticks } from "@/lib/units";
import styles from "./SectionProfile.module.css";

const H = 220;
const M = { top: 16, right: 16, bottom: 36, left: 56 };

export function SectionProfile({
  profile,
  loading,
  error,
  sectionMode,
  onStart,
  onClear,
  eyebrow = "Section profile",
  title,
  emptyText = "Choose Draw section, then click a start and an end point on the map.",
  showDraw = true,
}: {
  profile: Profile | null;
  loading: boolean;
  error: string | null;
  sectionMode: boolean;
  onStart: () => void;
  onClear: () => void;
  eyebrow?: string;
  title?: string;
  emptyText?: string;
  showDraw?: boolean;
}) {
  const titleId = useId();
  const bodyRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(720);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const pts = profile
    ? profile.distance_m
        .map((d, i) => [mToFt(d), mToFt(profile.elevation_m[i])] as const)
        .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
    : [];

  let chart: React.ReactNode = null;
  if (pts.length >= 2) {
    const xMax = pts[pts.length - 1][0];
    const ys = pts.map((p) => p[1]);
    let yMin = Math.min(...ys);
    let yMax = Math.max(...ys);
    const pad = Math.max((yMax - yMin) * 0.1, 2);
    yMin -= pad;
    yMax += pad;
    const iw = W - M.left - M.right;
    const ih = H - M.top - M.bottom;
    const sx = (x: number) => M.left + (x / (xMax || 1)) * iw;
    const sy = (y: number) => M.top + ih - ((y - yMin) / (yMax - yMin)) * ih;
    const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join("");
    const area = `${d}L${sx(xMax).toFixed(1)},${M.top + ih}L${sx(0).toFixed(1)},${M.top + ih}Z`;
    const xt = ticks(0, xMax, W < 480 ? 3 : 6);
    const yt = ticks(yMin, yMax, 4);
    const lo = Math.min(...ys);
    const hi = Math.max(...ys);
    chart = (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        role="img"
        aria-labelledby={titleId}
        width={W}
        height={H}
      >
        <title id={titleId}>
          {`Elevation section, ${Math.round(xMax).toLocaleString()} ft long, from ${Math.round(lo)} to ${Math.round(hi)} ft.`}
        </title>
        {yt.map((t) => (
          <g key={`y${t}`}>
            <line x1={M.left} x2={W - M.right} y1={sy(t)} y2={sy(t)} stroke="rgba(255,255,255,0.12)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <text x={M.left - 8} y={sy(t)} dy="0.32em" textAnchor="end" className={styles.tick}>
              {Math.round(t).toLocaleString()}
            </text>
          </g>
        ))}
        {xt.map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={M.top + ih} y2={M.top + ih + 4} stroke="rgba(255,255,255,0.26)" vectorEffect="non-scaling-stroke" />
            <text x={sx(t)} y={M.top + ih + 18} textAnchor="middle" className={styles.tick}>
              {Math.round(t).toLocaleString()}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={W - M.right} y1={M.top + ih} y2={M.top + ih} stroke="rgba(255,255,255,0.26)" vectorEffect="non-scaling-stroke" />
        <path d={area} fill="rgba(255,255,255,0.06)" />
        <path d={d} fill="none" stroke="#ffffff" strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        <text x={W - M.right} y={H - 4} textAnchor="end" className={styles.axisLabel}>Distance (ft)</text>
        <text x={4} y={M.top - 4} className={styles.axisLabel}>Elev. (ft)</text>
      </svg>
    );
  }

  return (
    <section className={`card ${styles.card}`} aria-labelledby="section-title">
      <div className={styles.head}>
        <div>
          <p className="app-eyebrow">{eyebrow}</p>
          <h2 id="section-title" className="app-h2">
            {title ?? (pts.length >= 2
              ? `${Math.round(Math.max(...pts.map((p) => p[1])) - Math.min(...pts.map((p) => p[1])))} ft of relief across ${Math.round(pts[pts.length - 1][0]).toLocaleString()} ft.`
              : "Cut a line across the land.")}
          </h2>
        </div>
        <div className={styles.actions}>
          {profile && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={onClear}>
              Clear
            </button>
          )}
          {showDraw && (
            <button type="button" className="btn btn-sm" aria-pressed={sectionMode} onClick={onStart}>
              {sectionMode ? "Click two points on the map" : "Draw section"}
            </button>
          )}
        </div>
      </div>
      <div ref={bodyRef} className={styles.body} aria-live="polite">
        {loading && <div className="progress progress-indeterminate" aria-label="Loading profile"><span /></div>}
        {error && <p className="error-text" role="alert">{error}</p>}
        {chart}
        {!chart && !loading && !error && (
          <p className="app-small">{emptyText}</p>
        )}
      </div>
    </section>
  );
}
