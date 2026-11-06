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


@lru_cache
def get_settings() -> Settings:
    return Settings()
