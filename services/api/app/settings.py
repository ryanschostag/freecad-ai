from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://cad:cad@db:5432/cad"
    artifact_dir: str = "/artifacts"
    rag_sources_config: str = "/config/rag_sources.yaml"
    llm_base_url: str = "http://llm:8000"
    freecad_worker_url: str = "http://freecad-worker:8070"
    storage_mode: str = "localfs"  # localfs or presigned (later)

settings = Settings()
