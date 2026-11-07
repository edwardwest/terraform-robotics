#!/usr/bin/env bash
# Build the knowledge base in the cloud (needs internet access to NRCS and the USDA data, which Cloud Run has).
#   infra/gcp/kb.sh PROJECT_ID [REGION] [rules|nrcs|plants|all]
# Uses the latest worker image; re-running replaces documents by key.
set -euo pipefail
PROJECT=${1:?project id}; REGION=${2:-us-west1}; WHAT=${3:-all}
IMAGE=$(gcloud run jobs describe terrain-worker --region="$REGION" --project="$PROJECT" --format='value(spec.template.spec.template.spec.containers[0].image)')
gcloud run jobs deploy kb-ingest --project="$PROJECT" --region="$REGION" --image="$IMAGE" \
  --service-account="terrain-worker@$PROJECT.iam.gserviceaccount.com" \
  --set-cloudsql-instances="$PROJECT:$REGION:terraform-db" --set-secrets=DATABASE_URL=database-url:latest \
  --set-env-vars="GCP_PROJECT=$PROJECT,GCP_REGION=$REGION,EMBEDDINGS=vertex,VERTEX_EMBED_REGION=us-central1" \
  --command=tr-worker --args="kb,$WHAT" --memory=2Gi --cpu=1 --task-timeout=7200s --max-retries=0 --quiet
gcloud run jobs execute kb-ingest --project="$PROJECT" --region="$REGION" --wait
