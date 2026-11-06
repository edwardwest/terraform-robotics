"use client";
import { useEffect, useRef, useState } from "react";
import { api, type Job } from "./api";

/** Polls GET /api/jobs/{id} every `intervalMs` until the job succeeds or fails. */
export function useJobPolling(jobId: string | null, intervalMs = 1500) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setJob(null);
    setError(null);
    if (!jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (cancelled) return;
        setJob(j);
        setError(null);
        if (j.status === "queued" || j.status === "running") timer.current = setTimeout(tick, intervalMs);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message);
        timer.current = setTimeout(tick, intervalMs * 2);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobId, intervalMs]);

  return { job, error };
}

export function jobProgress(job: Job | null): number | null {
  if (!job) return null;
  if (job.status === "succeeded") return 1;
  if (!job.step_count || job.step_index == null) return null;
  return Math.max(0, Math.min(1, (job.step_index - 1) / job.step_count));
}
