import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "cad-artifacts"
    s3_region: str = "us-east-1"

    # Local LLM (llama.cpp server or vLLM OpenAI-compatible)
    llm_base_url: str = os.getenv('LLM_BASE_URL')
    llm_model: str | None = None  # optional, depends on backend

settings = Settings()
