from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost/terraform"
    storage_url: str = "file:///tmp/terraform-data"  # or gs://bucket/prefix
    job_runner: str = "inline"  # inline | cloudrun
    gcp_project: str = ""
    gcp_region: str = "us-west1"
    terrain_job_name: str = "terrain-worker"
    max_upload_mb: int = 2048
    catchment_buffer_m: float = 150.0  # analyse this far beyond the boundary so inflowing water counts

    # Clerk authentication
    clerk_jwt_key: str = ""  # PEM "JWT public key" from the Clerk dashboard (networkless verification)
    clerk_jwks_url: str = ""  # or https://<frontend-api>/.well-known/jwks.json
    clerk_authorized_parties: str = ""  # comma-separated allowed origins, e.g. https://app.example.com
    auth_disabled: bool = False  # local development only: every request acts as one dev user


@lru_cache
def get_settings() -> Settings:
    return Settings()
