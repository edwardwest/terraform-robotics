// Signature motif: five concentric quarter-arcs anchored in a card corner.
// Radii 34/66/98/130/162, 1.25px stroke in stone-400.
type Corner = "top-right" | "bottom-right" | "bottom-left" | "top-left";

const RADII = [34, 66, 98, 130, 162];

export function ContourArcs({ corner = "bottom-right", className }: { corner?: Corner; className?: string }) {
  const size = 164;
  // Arcs centred on the anchored corner of the svg box.
  const cx = corner.includes("right") ? size : 0;
  const cy = corner.includes("bottom") ? size : 0;
  const pos: React.CSSProperties = {
    position: "absolute",
    pointerEvents: "none",
    [corner.includes("right") ? "right" : "left"]: 0,
    [corner.includes("bottom") ? "bottom" : "top"]: 0,
  };
  return (
    <svg
      className={className}
      style={pos}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {RADII.map((r) => (
        <circle key={r} cx={cx} cy={cy} r={r} stroke="#a3a29a" strokeWidth={1.25} />
      ))}
    </svg>
  );
}
