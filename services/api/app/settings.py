from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://cad:cad@db:5432/cad"
    artifact_staging_dir: str = "/artifacts_staging"
    rag_sources_config: str = "/config/rag_sources.yaml"
    llm_base_url: str = "http://llm:8000"
    redis_url: str = "redis://redis:6379/0"
    storage_mode: str = "minio"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "cad-artifacts"
    s3_region: str = "us-east-1"
settings = Settings()
