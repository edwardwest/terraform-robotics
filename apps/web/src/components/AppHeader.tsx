"use client";
import Link from "next/link";
import { Show, UserButton } from "@clerk/nextjs";
import { usePathname } from "next/navigation";
import { STEPS, STEP_PATH, stepOf } from "@/lib/steps";
import { AssistantButton } from "./assistant/AssistantDock";
import styles from "./AppHeader.module.css";

export function AppHeader() {
  const path = usePathname() || "/";
  const m = path.match(STEP_PATH);
  const isNew = path === "/projects/new";
  const projectId = m && m[1] !== "new" ? m[1] : null;
  const current = isNew ? "site" : stepOf(m?.[2]);
  const showSteps = isNew || !!projectId;

  return (
    <header className={styles.header}>
      <Link href="/" className={styles.logo} aria-label="Terraform Robotics, all projects">
        <img src="/brand/terraform-robotics-logo-horizontal.svg" alt="" height={22} width={176} />
      </Link>
      {showSteps && (
        <nav aria-label="Project steps" className={styles.nav}>
          <ol className={styles.steps}>
            {STEPS.map((s, i) => {
              const active = s.seg === current;
              const href = projectId ? `/projects/${projectId}/${s.seg}` : null;
              const content = (
                <>
                  <span className={styles.num}>{i + 1}</span>
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
          <AssistantButton />
          <UserButton />
        </Show>
      </div>
    </header>
  );
}
