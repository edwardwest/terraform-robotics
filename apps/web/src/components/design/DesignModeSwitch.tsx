// The two modes of the Design step: earthworks computed from the terrain (keylines, swales) and the master plan
// the person draws (everything else).
import Link from "next/link";
import styles from "./DesignView.module.css";

export function DesignModeSwitch({ projectId, mode }: { projectId: string; mode: "earthworks" | "plan" }) {
  return (
    <nav className={styles.modeSwitch} aria-label="Design mode">
      <Link href={`/projects/${projectId}/design`} className="chip" aria-current={mode === "earthworks" ? "page" : undefined}>
        Earthworks
      </Link>
      <Link href={`/projects/${projectId}/design?mode=plan`} className="chip" aria-current={mode === "plan" ? "page" : undefined}>
        Master plan
      </Link>
    </nav>
  );
}
