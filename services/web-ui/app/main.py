from __future__ import annotations

import os
from typing import Dict, Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8080").rstrip("/")

app = FastAPI(title="FreeCAD AI Web UI", docs_url=None, redoc_url=None, openapi_url=None)

# Serve static assets
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api(path: str, request: Request) -> Response:
    """Reverse-proxy API calls to the backend API container.

    Browser calls:  http://localhost:3000/api/v1/...
    We forward to:  {API_BASE_URL}/v1/...
    """
    url = f"{API_BASE_URL}/{path.lstrip('/')}"
    method = request.method

    # Forward query params and headers (minus Host)
    headers: Dict[str, str] = {k: v for k, v in request.headers.items() if k.lower() != "host"}

    body = await request.body()
    timeout_s = float(os.getenv("WEBUI_API_TIMEOUT_S", "900"))
    timeout = httpx.Timeout(timeout_s)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method,
            url,
            params=dict(request.query_params),
            content=body if body else None,
            headers=headers,
        )

    # Return response as-is
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
        headers={k: v for k, v in resp.headers.items() if k.lower() in {"content-type"}},
    )
