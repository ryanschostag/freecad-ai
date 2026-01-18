import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"

    # Artifact storage backend.
    #
    # - "s3": store artifacts in an S3-compatible object store (MinIO/AWS S3)
    # - "local": store artifacts on the container filesystem (useful for tests)
    storage_backend: str = os.getenv("STORAGE_BACKEND", "s3")

    # Base directory for local artifact storage when STORAGE_BACKEND=local.
    artifact_dir: str = os.getenv("ARTIFACT_DIR", "/data/artifacts")
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "cad-artifacts"
    s3_region: str = "us-east-1"

    # Local LLM (llama.cpp server or vLLM OpenAI-compatible)
    # Default matches docker-compose service name.
    llm_base_url: str = os.getenv('LLM_BASE_URL', 'http://llm:8000')
    llm_model: str | None = None  # optional, depends on backend

    # LLM request timeouts (seconds)
    llm_request_timeout_seconds: int = int(os.getenv('LLM_REQUEST_TIMEOUT_SECONDS', '180'))
    llm_connect_timeout_seconds: int = int(os.getenv('LLM_CONNECT_TIMEOUT_SECONDS', '10'))

    # API used for internal callbacks (persist job status/results outside Redis)
    api_base_url: str = os.getenv('API_BASE_URL', 'http://api:8080')

settings = Settings()
