#!/usr/bin/env bash
# Apply backend/sql/*.sql to Cloud SQL (all files are idempotent). Run from the repo root in Cloud Shell:
#   infra/gcp/migrate.sh PROJECT_ID [REGION]
# Uses the password inside the database-url secret, so nothing is rotated and running services keep working.
set -euo pipefail
PROJECT=${1:?project id}; REGION=${2:-us-west1}; SQL_INSTANCE=terraform-db
URL=$(gcloud secrets versions access latest --secret=database-url --project="$PROJECT")
DB_PASS=$(printf '%s' "$URL" | sed -E 's#^[^:]+://[^:]+:([^@]+)@.*#\1#')
PROXY=$(command -v cloud-sql-proxy || echo "$HOME/cloud-sql-proxy")
"$PROXY" --token "$(gcloud auth print-access-token)" --enable-builtin-metrics=false --port 6543 \
  "$PROJECT:$REGION:$SQL_INSTANCE" >/tmp/cloud-sql-proxy.log 2>&1 &
PROXY_PID=$!; trap 'kill $PROXY_PID 2>/dev/null || true' EXIT
for _ in $(seq 30); do pg_isready -h 127.0.0.1 -p 6543 >/dev/null 2>&1 && break; sleep 1; done
for f in backend/sql/*.sql; do
  echo "applying $f"
  PGPASSWORD=$DB_PASS psql -h 127.0.0.1 -p 6543 -U terraform -d terraform -v ON_ERROR_STOP=1 -q -f "$f"
done
echo "migrations applied"
