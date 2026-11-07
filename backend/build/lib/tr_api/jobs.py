"""Start background jobs: in-process threads locally, the Cloud Run Job on Google Cloud."""

from __future__ import annotations

import logging
import threading

from .config import get_settings

log = logging.getLogger(__name__)


def dispatch_terrain_job(job_id: str) -> None:
    settings = get_settings()
    if settings.job_runner == "inline":
        from tr_worker.terrain_job import run_terrain_job

        threading.Thread(target=run_terrain_job, args=(job_id,), daemon=True, name=f"terrain-{job_id}").start()
        return
    if settings.job_runner == "cloudrun":
        _run_cloud_run_job(job_id)
        return
    raise ValueError(f"Unknown JOB_RUNNER: {settings.job_runner}")


def _run_cloud_run_job(job_id: str) -> None:
    """Execute the terrain-worker Cloud Run Job with this job's ID as its argument."""
    from google.cloud import run_v2  # optional dependency: pip install .[gcp]

    s = get_settings()
    name = f"projects/{s.gcp_project}/locations/{s.gcp_region}/jobs/{s.terrain_job_name}"
    request = run_v2.RunJobRequest(
        name=name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[run_v2.RunJobRequest.Overrides.ContainerOverride(args=["terrain", job_id])]
        ),
    )
    run_v2.JobsClient().run_job(request=request)  # returns a long-running operation; progress is tracked in the jobs table
    log.info("Started Cloud Run Job %s for terrain job %s", name, job_id)
