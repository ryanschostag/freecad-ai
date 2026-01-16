from __future__ import annotations

from fastapi import APIRouter
import httpx

from app.settings import Settings


router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/health/llm")
async def health_llm():
    """Check whether the configured LLM service is reachable.

    We keep this intentionally tolerant because different llama.cpp
    server versions/models may or may not expose dedicated endpoints.
    """

    s = Settings()
    base = s.llm_base_url.rstrip("/")

    # Try a small set of common endpoints in order.
    candidates = [
        f"{base}/health",
        f"{base}/v1/models",
        f"{base}/",
    ]

    timeout = httpx.Timeout(2.0, connect=1.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        last_err: str | None = None
        for url in candidates:
            try:
                r = await client.get(url)
                if 200 <= r.status_code < 300:
                    return {"ok": True, "url": url, "status_code": r.status_code}
                last_err = f"{url} -> {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{url} -> {type(e).__name__}: {e}"

    return {"ok": False, "llm_base_url": base, "error": last_err}
