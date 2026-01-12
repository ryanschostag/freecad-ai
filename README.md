# CAD Agent (Local-first, Self-hosted)

This repo scaffolds a **self-hosted** “CAD Agent” system that:
- exposes a REST API for sessions/prompts
- runs a local LLM backend (CPU-first via llama.cpp; GPU-ready via vLLM profile)
- validates generated CAD macros via a FreeCAD headless worker (stubbed in this scaffold)
- manages authoritative RAG sources via a whitelist/blacklist YAML config
- stores everything in Postgres using a **star schema** (fact/dimension) for analytics
- stores artifacts on a mounted folder (and can be swapped to S3-compatible object storage later)

> No OpenAI or third-party hosted LLM services are used. This stack is designed to keep prompts and data local.

## Quick start (Windows 11 + Docker Desktop)

1. Create host folders:
   - `C:\cad-agent\data\artifacts`
   - `C:\cad-agent\data\models`
   - `C:\cad-agent\data\ragconfig`

2. Copy `rag_sources.yaml` to your host folder:
   - `C:\cad-agent\data\ragconfig\rag_sources.yaml`

3. Start the CPU profile:
```bash
docker compose --profile cpu up --build
```

4. Health check:
```bash
curl http://localhost:8080/v1/health
```

5. Create a session:
```bash
curl -X POST http://localhost:8080/v1/sessions -H "Content-Type: application/json" -d '{"title":"test"}'
```

6. Send a message:
```bash
curl -X POST http://localhost:8080/v1/sessions/<session_id>/messages -H "Content-Type: application/json" -d '{"content":"Create a 20mm cube in FreeCAD python."}'
```

## GPU host (Linux + CUDA) later

Use the GPU profile and override:
```bash
docker compose --profile gpu -f docker-compose.yml -f docker-compose.gpu.override.yml up --build
```

## API contract

The REST contract is in:
- `api_spec.yaml`

## Star schema analytics

Facts:
- `fact_prompt`, `fact_completion`, `fact_validation_result`, `fact_citation`,
  `fact_artifact_event`, `fact_source_change`, `fact_ingest_run`, `fact_ingest_run_item`

Dimensions:
- `dim_time`, `dim_session`, `dim_user`, `dim_model`, `dim_source`, `dim_artifact`, `dim_validation_rule`

Example: prompts per session
```sql
SELECT session_id, COUNT(*) AS prompts
FROM fact_prompt
GROUP BY session_id
ORDER BY prompts DESC;
```

## Testing

Run unit/API tests (from repo root):
```bash
docker compose run --rm api pytest -q
```

## Notes / TODO

- The FreeCAD worker in this scaffold is a stub (no real FreeCAD execution). Replace the stub with a headless FreeCAD container/job runner.
- The RAG service currently implements whitelist reconciliation + logging; the actual crawler/downloader/indexer is stubbed.
