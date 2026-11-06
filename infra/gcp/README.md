# Google Cloud deployment

Three pieces, all built by `cloudbuild.yaml`:

| Piece | Google Cloud service | Image |
| --- | --- | --- |
| Web app (Next.js) | Cloud Run service `web` | `apps/web/Dockerfile` |
| API (FastAPI) | Cloud Run service `api` | `backend/Dockerfile` |
| Terrain worker | Cloud Run Job `terrain-worker` | `backend/Dockerfile.worker` (adds PDAL, GDAL, py3dep) |

Data: Cloud SQL for PostgreSQL 16 with PostGIS; uploads and DEMs in a Cloud Storage bucket.

## One-time setup

```bash
PROJECT=your-project; REGION=us-west1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com storage.googleapis.com

# Images
gcloud artifacts repositories create terraform-robotics --repository-format=docker --location=$REGION

# Database
gcloud sql instances create terraform-db --database-version=POSTGRES_16 --region=$REGION --tier=db-custom-1-3840
gcloud sql databases create terraform --instance=terraform-db
gcloud sql users create terraform --instance=terraform-db --password=CHANGE_ME
# then connect (Cloud SQL Studio or the proxy) and run backend/sql/001_init.sql — it enables PostGIS

# Storage
gcloud storage buckets create gs://$PROJECT-terraform-data --location=$REGION --uniform-bucket-level-access

# Connection string as a secret (Cloud SQL unix socket)
printf 'postgresql+psycopg://terraform:CHANGE_ME@/terraform?host=/cloudsql/%s:%s:terraform-db' $PROJECT $REGION \
  | gcloud secrets create database-url --data-file=-

# Service accounts
gcloud iam service-accounts create api
gcloud iam service-accounts create terrain-worker
for SA in api terrain-worker; do
  for ROLE in roles/cloudsql.client roles/secretmanager.secretAccessor; do
    gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA@$PROJECT.iam.gserviceaccount.com --role=$ROLE
  done
  gcloud storage buckets add-iam-policy-binding gs://$PROJECT-terraform-data \
    --member=serviceAccount:$SA@$PROJECT.iam.gserviceaccount.com --role=roles/storage.objectAdmin
done
# the API starts worker executions with argument overrides
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:api@$PROJECT.iam.gserviceaccount.com --role=roles/run.developer
gcloud iam service-accounts add-iam-policy-binding terrain-worker@$PROJECT.iam.gserviceaccount.com \
  --member=serviceAccount:api@$PROJECT.iam.gserviceaccount.com --role=roles/iam.serviceAccountUser
```

## Deploy

```bash
gcloud builds submit --config infra/gcp/cloudbuild.yaml --substitutions=_REGION=$REGION,SHORT_SHA=$(git rev-parse --short HEAD)
```

## Before real users

- **Authentication is not wired yet.** The API is deployed publicly so the web app's server-side proxy can reach it. Add Identity Platform (Firebase Auth) sign-in and verify ID tokens in the API, or put both services behind a load balancer with Identity-Aware Proxy, before storing client data.
- Large LiDAR uploads should go straight to Cloud Storage via signed URLs rather than through the API (Cloud Run caps request bodies at 32 MiB). The current upload endpoint suits DEMs, contour files and small point clouds.
- The worker's public-elevation fetch needs outbound access to USGS services (default on Cloud Run).
