"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Project } from "@/lib/api";
import { formatAcres } from "@/lib/units";
import { ContourArcs } from "./ContourArcs";
import { IconPlus } from "./Icons";
import styles from "./ProjectList.module.css";

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

export function ProjectList() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <p className="app-eyebrow">Projects</p>
          <h1 className="app-display">Your land.</h1>
        </div>
        <Link href="/projects/new" className="btn btn-primary">
          <IconPlus /> New project
        </Link>
      </div>

      {error && (
        <p className="error-text" role="alert">
          Projects did not load. {error}
        </p>
      )}

      {!projects && !error && <p className="app-small" aria-live="polite">Loading projects.</p>}

      {projects && projects.length === 0 && (
        <section className={`card-solid ${styles.empty}`} aria-labelledby="empty-title">
          <ContourArcs corner="bottom-right" />
          <p className="app-eyebrow">No projects yet</p>
          <h2 id="empty-title" className="app-h1">Start with the land.</h2>
          <p className="app-body">Set a boundary, bring your ground data, and see where the water goes.</p>
          <Link href="/projects/new" className="btn btn-primary">
            <IconPlus /> New project
          </Link>
        </section>
      )}

      {projects && projects.length > 0 && (
        <ul className={styles.grid}>
          {projects.map((p) => (
            <li key={p.id}>
              <Link href={`/projects/${p.id}/terrain`} className={`card card-interactive ${styles.card}`}>
                <span className={styles.figure}>
                  <span className="app-numeral">{formatAcres(p.area_m2)}</span>
                  <span className="app-small">acres</span>
                </span>
                <span className="app-title">{p.name}</span>
                <span className="app-small">
                  {p.address ? `${p.address} · ` : ""}
                  Created {dateFmt.format(new Date(p.created_at))}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
