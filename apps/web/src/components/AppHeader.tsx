"use client";
import Link from "next/link";
import { Show, UserButton } from "@clerk/nextjs";
import { usePathname } from "next/navigation";
import styles from "./AppHeader.module.css";

const STEPS = [
  { n: 1, label: "Site", seg: "site" },
  { n: 2, label: "Survey", seg: "survey" },
  { n: 3, label: "Terrain", seg: "terrain" },
  { n: 4, label: "Design", seg: "design" },
  { n: 5, label: "Estimate", seg: "estimate" },
] as const;

export function AppHeader() {
  const path = usePathname() || "/";
  const m = path.match(/^\/projects\/([^/]+)\/(site|survey|terrain|design|estimate|export)/);
  const isNew = path === "/projects/new";
  const projectId = m && m[1] !== "new" ? m[1] : null;
  const current = isNew ? "site" : m?.[2] === "export" ? "estimate" : m?.[2] ?? null;
  const showSteps = isNew || !!projectId;

  return (
    <header className={styles.header}>
      <Link href="/" className={styles.logo} aria-label="Terraform Robotics, all projects">
        <img src="/brand/terraform-robotics-logo-horizontal.svg" alt="" height={22} width={176} />
      </Link>
      {showSteps && (
        <nav aria-label="Project steps" className={styles.nav}>
          <ol className={styles.steps}>
            {STEPS.map((s) => {
              const active = s.seg === current;
              const href = projectId ? `/projects/${projectId}/${s.seg}` : null;
              const content = (
                <>
                  <span className={styles.num}>{s.n}</span>
                  <span className={styles.label}>{s.label}</span>
                </>
              );
              return (
                <li key={s.seg}>
                  {href ? (
                    <Link
                      href={href}
                      className={`${styles.step} ${active ? styles.active : ""}`}
                      aria-current={active ? "step" : undefined}
                    >
                      {content}
                    </Link>
                  ) : (
                    <span
                      className={`${styles.step} ${active ? styles.active : styles.disabled}`}
                      aria-current={active ? "step" : undefined}
                      aria-disabled={!active || undefined}
                    >
                      {content}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      )}
      <div className={styles.account}>
        <Show when="signed-in">
          <UserButton />
        </Show>
      </div>
    </header>
  );
}
