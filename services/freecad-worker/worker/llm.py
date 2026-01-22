from __future__ import annotations

import os
import time

import httpx

from worker.settings import settings


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def chat(
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 1200,
    *,
    timeout_s: float | None = None,
) -> str:
    """Uses an OpenAI-compatible chat endpoint.

    Works with llama.cpp server (OpenAI-compatible) and vLLM OpenAI server.

    Notes on timeouts (CPU profile):
    - The first request can be slow due to model load/warmup.
    - Longer generations can exceed httpx defaults.

    Config:
    - LLM_HTTP_TIMEOUT_S: overall request timeout (seconds)
    - LLM_HTTP_CONNECT_TIMEOUT_S: connect timeout (seconds)
    - LLM_HTTP_MAX_ATTEMPTS: retry count for transient timeouts
    - LLM_HTTP_RETRY_BACKOFF_S: base backoff (seconds), multiplied by attempt number
    """
    url = settings.llm_base_url.rstrip("/")
    endpoint = url + "/v1/chat/completions"
    payload = {
        "model": settings.llm_model or "local-model",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # Resolve timeouts: explicit arg > env > settings defaults
    req_timeout_default = float(settings.llm_request_timeout_seconds)
    connect_timeout_default = float(settings.llm_connect_timeout_seconds)

    req_timeout = (
        float(timeout_s)
        if timeout_s is not None
        else _env_float("LLM_HTTP_TIMEOUT_S", req_timeout_default)
    )
    connect_timeout = _env_float("LLM_HTTP_CONNECT_TIMEOUT_S", connect_timeout_default)

    # Retries for transient timeouts during warmup
    max_attempts = max(1, _env_int("LLM_HTTP_MAX_ATTEMPTS", 2))
    backoff_s = _env_float("LLM_HTTP_RETRY_BACKOFF_S", 1.0)

    client_timeout = httpx.Timeout(req_timeout, connect=connect_timeout)

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=client_timeout) as client:
                r = client.post(endpoint, json=payload)
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_exc = e
            if attempt >= max_attempts:
                raise
            # linear backoff; keep it simple and predictable
            time.sleep(backoff_s * attempt)

    assert last_exc is not None
    raise last_exc
