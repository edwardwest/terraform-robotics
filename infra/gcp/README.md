# Google Cloud deployment

Three pieces, all built by `cloudbuild.yaml`:

| Piece | Google Cloud service | Image |
| --- | --- | --- |
| Web app (Next.js) | Cloud Run service `web` | `apps/web/Dockerfile` |
| API (FastAPI) | Cloud Run service `api` | `backend/Dockerfile` |
| Terrain worker | Cloud Run Job `terrain-worker` | `backend/Dockerfile.worker` (adds PDAL, GDAL, py3dep) |

Data: Cloud SQL for PostgreSQL 16 with PostGIS; uploads and DEMs in a Cloud Storage bucket.

## One-time setup

In Cloud Shell, from a clone of this repo:

```bash
infra/gcp/setup.sh PROJECT_ID BILLING_ACCOUNT_ID us-west1
```

It links billing, enables APIs, and creates the Artifact Registry repo, Cloud SQL (PostgreSQL 16, `db-f1-micro`), the schema from `backend/sql`, the data bucket, the `database-url` secret (with a generated password nobody sees), and service accounts `tr-api`, `terrain-worker` and `tr-web` with their roles. It is safe to re-run.

Then add the Clerk secret key (never commit it):

```bash
gcloud secrets versions add clerk-secret-key --data-file=-   # paste the key, then Ctrl-D
```

## Deploy

```bash
gcloud builds submit --config infra/gcp/cloudbuild.yaml --substitutions=_REGION=us-west1,SHORT_SHA=$(git rev-parse --short HEAD)
```

## Before real users

- **Authentication is Clerk.** Every API route except `/api/health` requires a valid Clerk session token, and users only see their own projects. Set `_WEB_ORIGIN` to the web service URL after the first deploy so the API also checks which site issued each token. The development Clerk instance is fine for testing; create a production instance in Clerk (with your own domain) before real users.
- Large LiDAR uploads should go straight to Cloud Storage via signed URLs rather than through the API (Cloud Run caps request bodies at 32 MiB). The current upload endpoint suits DEMs, contour files and small point clouds.
- The worker's public-elevation fetch needs outbound access to USGS services (default on Cloud Run).
