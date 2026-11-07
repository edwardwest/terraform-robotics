// Looping day-and-night scene for long-running jobs, drawn from the logo mark (sun over two hills):
// the sun rises, a cloud rains, the sun sets, the moon and stars come out, and the day starts again.
// Decorative only; the progress bar and step text carry the real status.
import styles from "./DayCycle.module.css";

// The logo's hills in its own 100 x 68 coordinates; the scene stretches them to 200 wide and adds sky above.
const HILL_TOP =
  "M0,26.5 C9,22.5 18,18 27,18 C40,18 55,29 66,32 C72,34 77,33 82,34 C88,35 94,38 100,41 L100,60.4 C90,59 78,57 65,53 C55,50 44,42 33,38.5 C24,35.5 12,35.4 0,35.9 Z";
const HILL_BASE = "M0,38.2 C12,37.7 24,37.8 33,41 C44,45 55,52.5 65,55.5 C78,59.5 90,61.5 100,62.7 L100,67.6 L0,67.6 Z";
// Everything above the top hill's skyline, so the sun and moon set behind the land.
const SKY = "M0,-20 H100 V41 C94,38 88,35 82,34 C77,33 72,34 66,32 C55,29 40,18 27,18 C18,18 9,22.5 0,26.5 Z";

const STARS: [number, number, number][] = [
  [18, 2, 1], [36, -6, 0.8], [58, 8, 0.9], [80, -8, 1.1], [104, 3, 0.7], [116, -2, 0.8], [134, 12, 1], [166, -4, 1.1], [186, 6, 0.8],
];
const DROPS = [130, 135, 140, 145, 150];

export function DayCycle({ className }: { className?: string }) {
  return (
    <svg className={`${styles.scene} ${className ?? ""}`} viewBox="0 -14 200 82" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id="daycycle-sky">
          <path d={SKY} transform="scale(2 1)" />
        </clipPath>
      </defs>

      <g clipPath="url(#daycycle-sky)">
        <g className={styles.stars}>
          {STARS.map(([x, y, r], i) => (
            <circle key={i} className={styles.star} cx={x} cy={y} r={r} style={{ animationDelay: `${(i * 0.37) % 2}s` }} />
          ))}
        </g>

        <g className={styles.moon}>
          <path transform="translate(90 6)" d="M0,-7 A7,7 0 1,0 0,7 A3.5,7 0 1,1 0,-7 Z" />
        </g>

        <g className={styles.sun}>
          <circle cx={150} cy={8} r={9} />
        </g>

        <g className={styles.rain}>
          {DROPS.map((x, i) => (
            <line key={x} className={styles.drop} x1={x} y1={17} x2={x - 1.5} y2={21}
              style={{ animationDelay: `${(i * 0.23) % 0.7}s` }} />
          ))}
        </g>

        <g className={styles.cloud}>
          <g transform="translate(138 9)">
            <circle cx={-7} cy={2} r={5.5} />
            <circle cx={1} cy={-2} r={7.5} />
            <circle cx={9} cy={2} r={5.5} />
            <rect x={-12.5} y={1} width={27} height={6.5} rx={3.25} />
          </g>
        </g>
      </g>

      <g transform="scale(2 1)" className={styles.land}>
        <path d={HILL_TOP} />
        <path d={HILL_BASE} />
      </g>
    </svg>
  );
}
