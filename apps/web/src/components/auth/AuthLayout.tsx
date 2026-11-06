import { ContourArcs } from "@/components/ContourArcs";
import styles from "./AuthLayout.module.css";

export function AuthLayout({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className={styles.wrap}>
      <section className={styles.intro}>
        <p className={styles.eyebrow}>Terraform Robotics</p>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.body}>
          Map the land, see where the water goes, and design the interventions that keep it there.
        </p>
        <div className={styles.motif}>
          <ContourArcs corner="bottom-right" />
        </div>
      </section>
      <section className={styles.form}>{children}</section>
    </div>
  );
}
