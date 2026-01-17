from __future__ import annotations
import httpx
from worker.settings import settings

def chat(
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 1200,
    *,
    timeout_s: float | None = None,
) -> str:
    """Uses an OpenAI-compatible chat endpoint.
    Works with llama.cpp server (OpenAI-compatible) and vLLM OpenAI server.
    """
    url = settings.llm_base_url.rstrip("/")
    endpoint = url + "/v1/chat/completions"
    payload = {
        "model": settings.llm_model or "local-model",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req_timeout = float(timeout_s) if timeout_s is not None else float(settings.llm_request_timeout_seconds)
    client_timeout = httpx.Timeout(req_timeout, connect=float(settings.llm_connect_timeout_seconds))
    with httpx.Client(timeout=client_timeout) as client:
        r = client.post(endpoint, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
