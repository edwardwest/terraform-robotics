#!/usr/bin/env bash
# One-time setup of a fresh Google Cloud project for Terraform Robotics. Safe to re-run.
# Run from the repo root in Cloud Shell:
#   infra/gcp/setup.sh PROJECT_ID BILLING_ACCOUNT_ID [REGION]
# Then add the Clerk secret key (printed instructions) and run the deploy in README.md.
set -euo pipefail
PROJECT=${1:?project id}; BILLING=${2:?billing account id}; REGION=${3:-us-west1}
SQL_INSTANCE=terraform-db; BUCKET=gs://$PROJECT-terraform-data
say() { printf '\n== %s\n' "$*"; }

say "Billing and APIs"
gcloud billing projects link "$PROJECT" --billing-account="$BILLING" >/dev/null
gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com
NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
BUILD_SA=$NUM-compute@developer.gserviceaccount.com   # Cloud Build's default service account in new projects

say "Artifact Registry"
gcloud artifacts repositories describe terraform-robotics --location="$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create terraform-robotics --repository-format=docker --location="$REGION"

say "Cloud SQL (PostgreSQL 16, smallest tier; takes ~10 minutes the first time)"
gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1 ||
  gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 --edition=ENTERPRISE \
    --tier=db-f1-micro --region="$REGION" --storage-size=10 --storage-auto-increase
gcloud sql databases describe terraform --instance="$SQL_INSTANCE" >/dev/null 2>&1 ||
  gcloud sql databases create terraform --instance="$SQL_INSTANCE"
DB_PASS=$(openssl rand -hex 24)   # never printed; lives only in Secret Manager
if gcloud sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx terraform; then
  gcloud sql users set-password terraform --instance="$SQL_INSTANCE" --password="$DB_PASS"
else
  gcloud sql users create terraform --instance="$SQL_INSTANCE" --password="$DB_PASS"
fi

say "Secrets"
gcloud secrets describe database-url >/dev/null 2>&1 || gcloud secrets create database-url --replication-policy=automatic
printf 'postgresql+psycopg://terraform:%s@/terraform?host=/cloudsql/%s:%s:%s' "$DB_PASS" "$PROJECT" "$REGION" "$SQL_INSTANCE" |
  gcloud secrets versions add database-url --data-file=- >/dev/null
gcloud secrets describe clerk-secret-key >/dev/null 2>&1 || gcloud secrets create clerk-secret-key --replication-policy=automatic

say "Schema (via Cloud SQL Auth Proxy)"
PROXY=$(command -v cloud-sql-proxy || true)
if [ -z "$PROXY" ]; then
  PROXY=$HOME/cloud-sql-proxy
  curl -sSLo "$PROXY" https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.linux.amd64
  chmod +x "$PROXY"
fi
"$PROXY" --token "$(gcloud auth print-access-token)" --enable-builtin-metrics=false --port 6543 "$PROJECT:$REGION:$SQL_INSTANCE" >/tmp/cloud-sql-proxy.log 2>&1 &
PROXY_PID=$!; trap 'kill $PROXY_PID 2>/dev/null || true' EXIT
for _ in $(seq 30); do pg_isready -h 127.0.0.1 -p 6543 >/dev/null 2>&1 && break; sleep 1; done
for f in backend/sql/*.sql; do
  echo "applying $f"
  PGPASSWORD=$DB_PASS psql -h 127.0.0.1 -p 6543 -U terraform -d terraform -v ON_ERROR_STOP=1 -q -f "$f"
done

say "Storage"
gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1 ||
  gcloud storage buckets create "$BUCKET" --location="$REGION" --uniform-bucket-level-access

say "Service accounts and roles"
for SA in tr-api terrain-worker tr-web; do
  gcloud iam service-accounts describe "$SA@$PROJECT.iam.gserviceaccount.com" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$SA"
done
sleep 5   # new service accounts take a moment to become visible to IAM
bind() { gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$1" --role="$2" --condition=None >/dev/null; }
for SA in tr-api terrain-worker; do
  M=$SA@$PROJECT.iam.gserviceaccount.com
  bind "$M" roles/cloudsql.client
  gcloud secrets add-iam-policy-binding database-url --member="serviceAccount:$M" --role=roles/secretmanager.secretAccessor >/dev/null
  gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$M" --role=roles/storage.objectAdmin >/dev/null
done
gcloud secrets add-iam-policy-binding clerk-secret-key --member="serviceAccount:tr-web@$PROJECT.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor >/dev/null
# the API starts worker executions with argument overrides
bind "tr-api@$PROJECT.iam.gserviceaccount.com" roles/run.developer
gcloud iam service-accounts add-iam-policy-binding "terrain-worker@$PROJECT.iam.gserviceaccount.com" \
  --member="serviceAccount:tr-api@$PROJECT.iam.gserviceaccount.com" --role=roles/iam.serviceAccountUser >/dev/null
# Cloud Build: push images, deploy Cloud Run, act as the runtime service accounts, write logs
for ROLE in roles/run.admin roles/iam.serviceAccountUser roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  bind "$BUILD_SA" "$ROLE"
done

say "Done"
if ! gcloud secrets versions list clerk-secret-key --format='value(name)' | grep -q .; then
  echo "Next: add the Clerk secret key (Clerk dashboard > API keys), then deploy:"
  echo "  gcloud secrets versions add clerk-secret-key --data-file=-   # paste the key, then Ctrl-D"
fi
