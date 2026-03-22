from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pydantic reserves some namespaces (like `model_`) for internal use.
    # We use `model_*` fields for model execution metadata; disable the warning.
    model_config = SettingsConfigDict(protected_namespaces=())
    # Default to localhost so running `pytest` from the host works.
    # docker-compose.yml overrides this to `@db:5432` for in-container use.
    database_url: str = "postgresql+psycopg://cad:cad@localhost:5432/cad"
    artifact_staging_dir: str = "/artifacts_staging"
    rag_sources_config: str = "/config/rag_sources.yaml"
    llm_base_url: str = "http://freecad-ai-llm:8000"

    # Queue/job timeouts
    # - default_job_timeout_seconds: default user-visible timeout for a job
    # - job_timeout_buffer_seconds: buffer added to the RQ job timeout so that
    #   internal timeouts (LLM call, FreeCAD exec) can raise/fail cleanly first
    default_job_timeout_seconds: int = 900
    job_timeout_buffer_seconds: int = 60

    # LLM readiness/health timeouts (seconds)
    llm_health_timeout_seconds: float = 2.0
    llm_ready_timeout_seconds: float = 300.0
    queue_worker_heartbeat_timeout_seconds: float = 120.0
    redis_url: str = "redis://redis:6379/0"
    storage_mode: str = "minio"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "cad-artifacts"
    s3_region: str = "us-east-1"

    # Model execution metadata (provided by Docker for each profile)
    # These values can be persisted into DimModel for metrics.
    model_id: str = "cpu-default"
    model_backend: str = "llama.cpp"
    model_device: str = "cpu"

    # Test/dev option: run jobs synchronously in-process instead of relying on
    # an external RQ worker. Disabled by default; enabled in the docker-compose
    # test profile to keep API TestClient runs deterministic.
    inline_jobs: bool = Field(default=False, validation_alias="CAD_AGENT_INLINE_JOBS")


settings = Settings()
