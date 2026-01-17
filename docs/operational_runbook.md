
If jobs stuck in started:
1. Check worker logs
2. Verify Redis connectivity
3. Confirm LLM /health endpoint

If API returns 500:
1. Inspect FastAPI logs
2. Check DB migrations
3. Validate environment variables

Profile switching:
docker compose --profile test up -d
docker compose --profile cpu up -d
