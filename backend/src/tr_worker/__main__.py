"""Worker entry point: `tr-worker terrain <job_id>` (the Cloud Run Job's container command)."""

import logging
import sys


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2 or args[0] != "terrain":
        print("usage: tr-worker terrain <job_id>", file=sys.stderr)
        return 2
    from .terrain_job import run_terrain_job

    run_terrain_job(args[1])
    from tr_api.db import fetch_one

    job = fetch_one("SELECT status FROM jobs WHERE id = :id", id=args[1])
    return 0 if job and job["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
