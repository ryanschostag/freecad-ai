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
    # Default matches docker-compose service name.
    # The compose stack routes the worker to the explicit alias below, so keep
    # the code default aligned with that runtime configuration even when unit
    # tests do not inject LLM_BASE_URL into the test-runner environment.
    llm_base_url: str = os.getenv('LLM_BASE_URL', 'http://freecad-ai-llm:8000')
    llm_model: str | None = None  # optional, depends on backend

    # LLM request timeouts (seconds)
    llm_request_timeout_seconds: int = int(os.getenv('LLM_REQUEST_TIMEOUT_SECONDS', '180'))
    llm_connect_timeout_seconds: int = int(os.getenv('LLM_CONNECT_TIMEOUT_SECONDS', '10'))
    llm_ctx_size: int = int(os.getenv('LLM_CTX_SIZE', '4096'))
    llm_ctx_reserve_tokens: int = int(os.getenv('LLM_CTX_RESERVE_TOKENS', '256'))

    # Persisted LLM training state mounted from the host for reuse across rebuilds.
    llm_state_dir: str = os.getenv('LLM_STATE_DIR', '/data/llm/state')

    # API used for internal callbacks (persist job status/results outside Redis)
    api_base_url: str = os.getenv('API_BASE_URL', 'http://api:8080')

settings = Settings()
