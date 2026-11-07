#!/usr/bin/env bash
# Run knowledge-base ingestion from Cloud Shell against Cloud SQL (through the proxy). Use this for sources that
# don't answer Cloud Run's network (eFOTG returns 403 to Cloud Run). Run from the repo root:
#   infra/gcp/kb-local.sh PROJECT_ID [REGION] [nrcs|rules|plants|all] [extra args, e.g. --limit 5 --state CA]
# Needs application-default credentials for Vertex embeddings: gcloud auth login --update-adc
set -euo pipefail
PROJECT=${1:?project id}; REGION=${2:-us-west1}; WHAT=${3:-nrcs}; shift $(( $# < 3 ? $# : 3 ))
URL=$(gcloud secrets versions access latest --secret=database-url --project="$PROJECT")
DB_PASS=$(printf '%s' "$URL" | sed -E 's#^[^:]+://[^:]+:([^@]+)@.*#\1#')
PROXY=$(command -v cloud-sql-proxy || echo "$HOME/cloud-sql-proxy")
"$PROXY" --token "$(gcloud auth print-access-token)" --enable-builtin-metrics=false --port 6543 \
  "$PROJECT:$REGION:terraform-db" >/tmp/cloud-sql-proxy.log 2>&1 &
PROXY_PID=$!; trap 'kill $PROXY_PID 2>/dev/null || true' EXIT
for _ in $(seq 30); do pg_isready -h 127.0.0.1 -p 6543 >/dev/null 2>&1 && break; sleep 1; done

VENV=$HOME/.venvs/tr-kb
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q httpx sqlalchemy "psycopg[binary]" pypdf pyyaml pydantic-settings google-auth requests

DB_ENC=$("$VENV/bin/python" -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$DB_PASS")
export DATABASE_URL="postgresql+psycopg://terraform:${DB_ENC}@127.0.0.1:6543/terraform"
export GCP_PROJECT=$PROJECT GCP_REGION=$REGION EMBEDDINGS=vertex VERTEX_EMBED_REGION=us-central1
PYTHONPATH=backend/src "$VENV/bin/python" -c '
import logging, sys
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
from tr_kb.ingest import main
sys.exit(main(sys.argv[1:]))' "$WHAT" "$@"
