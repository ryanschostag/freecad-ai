from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    # Default to localhost so running `pytest` from the host works.
    # docker-compose.yml overrides this to `@db:5432` for in-container use.
    database_url: str = "postgresql+psycopg://cad:cad@localhost:5432/cad"
    artifact_staging_dir: str = "/artifacts_staging"
    rag_sources_config: str = "/config/rag_sources.yaml"
    llm_base_url: str = "http://llm:8000"

    # Queue/job timeouts
    # - default_job_timeout_seconds: default user-visible timeout for a job
    # - job_timeout_buffer_seconds: buffer added to the RQ job timeout so that
    #   internal timeouts (LLM call, FreeCAD exec) can raise/fail cleanly first
    default_job_timeout_seconds: int = 900
    job_timeout_buffer_seconds: int = 60

    # LLM health check timeout (seconds)
    llm_health_timeout_seconds: float = 2.0
    redis_url: str = "redis://redis:6379/0"
    storage_mode: str = "minio"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "cad-artifacts"
    s3_region: str = "us-east-1"
settings = Settings()
