from __future__ import annotations
import httpx
from worker.settings import settings

def chat(messages: list[dict[str,str]], temperature: float = 0.1, max_tokens: int = 1200) -> str:
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
    with httpx.Client(timeout=180.0) as client:
        r = client.post(endpoint, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
