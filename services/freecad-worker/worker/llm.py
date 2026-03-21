from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

from worker.settings import settings


LLM_LOADING_HINTS = (
    "loading model",
    "model is loading",
    "model loading",
    "loading",
    "initializing",
    "warm",
    "slot",
)


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


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_text(item)
            if text:
                parts.append(text)
        return "".join(parts)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("output_text"), str):
            return value["output_text"]
        if "content" in value:
            return _extract_text(value.get("content"))
        if "message" in value:
            return _extract_text(value.get("message"))
    return ""


def _strip_code_fences(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        body = lines[1:-1]
        if body and body[0].strip().lower() in {"python", "py"}:
            body = body[1:]
        return "\n".join(body).strip()
    return s


def _strip_thinking(text: str) -> str:
    return re.sub(r"^\s*<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _normalize_generated_text(text: str) -> str:
    return _strip_code_fences(_strip_thinking(text))


def _response_preview(data: Any) -> str:
    try:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        raw = repr(data)
    raw = raw.replace("\n", "\\n")
    return raw[:500]


def _extract_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice0 = choices[0]
        if isinstance(choice0, dict):
            for candidate in (
                choice0.get("message"),
                choice0.get("delta"),
                choice0.get("text"),
                choice0.get("content"),
            ):
                text = _extract_text(candidate)
                if text.strip():
                    return _normalize_generated_text(text)
    for candidate in (data.get("message"), data.get("content"), data.get("text")):
        text = _extract_text(candidate)
        if text.strip():
            return _normalize_generated_text(text)
    return ""


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    """Render messages as ChatML for Qwen/llama.cpp native /completion calls."""
    blocks: list[str] = []
    for message in messages:
        role = str(message.get("role", "user")).strip().lower() or "user"
        content = str(message.get("content", ""))
        blocks.append(f"<|im_start|>{role}\n{content}\n<|im_end|>")
    blocks.append("<|im_start|>assistant\n")
    return "\n".join(blocks)


def _sanitize_stop_sequences(stop: list[str] | None) -> list[str] | None:
    if not stop:
        return stop
    sanitized: list[str] = []
    seen: set[str] = set()
    for item in stop:
        s = str(item)
        if not s or s == "```":
            continue
        if s not in seen:
            seen.add(s)
            sanitized.append(s)
    return sanitized or None


def _candidate_base_urls(base_url: str) -> list[str]:
    candidates: list[str] = []

    def add(url: str) -> None:
        normalized = str(url or "").strip().rstrip("/")
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    host_swaps = {
        "http://llm:8000": "http://freecad-ai-llm:8000",
        "http://freecad-ai-llm:8000": "http://llm:8000",
        "http://llm-cuda:8000": "http://llm-gpu:8000",
        "http://llm-gpu:8000": "http://llm-cuda:8000",
    }
    host_gateway_swaps = {
        "http://llm:8000": "http://host.docker.internal:8000",
        "http://freecad-ai-llm:8000": "http://host.docker.internal:8000",
        "http://llm-cuda:8000": "http://host.docker.internal:8000",
        "http://llm-gpu:8000": "http://host.docker.internal:8000",
        "http://llm-fake:8000": "http://host.docker.internal:8001",
        "http://freecad-ai-llm-fake:8000": "http://host.docker.internal:8001",
    }

    add(base_url)
    add(host_swaps.get(base_url, ""))
    add(host_gateway_swaps.get(base_url, ""))

    env_url = os.getenv("LLM_BASE_URL", "")
    env_url = str(env_url or "").strip().rstrip("/")
    if env_url and env_url not in candidates:
        add(env_url)
        add(host_swaps.get(env_url, ""))
        add(host_gateway_swaps.get(env_url, ""))

    return candidates


def _response_body_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="ignore")
    if isinstance(content, str):
        return content
    return ""


def _is_loading_response(response: object) -> bool:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code not in {408, 425, 429, 500, 502, 503, 504}:
        return False
    body = _response_body_text(response).lower()
    return any(hint in body for hint in LLM_LOADING_HINTS) or status_code in {502, 503, 504}


def _build_http_client(client_timeout: httpx.Timeout) -> httpx.Client:
    """Create an httpx client for internal Docker calls without inheriting ambient env proxies.

    Unit tests monkeypatch httpx.Client with lightweight lambdas that only accept the
    timeout kwarg. Fall back to a timeout-only constructor when the replacement does
    not accept trust_env so tests can exercise the chat logic without depending on
    the concrete httpx.Client signature.
    """
    try:
        return httpx.Client(timeout=client_timeout, trust_env=False)
    except TypeError:
        return httpx.Client(timeout=client_timeout)


def _wait_for_inference_ready(
    client: httpx.Client,
    base_url: str,
    *,
    request_timeout_s: float,
    max_wait_s: float,
) -> None:
    """Wait until the LLM can answer a tiny inference request, not just /health."""
    deadline = time.monotonic() + max(0.0, max_wait_s)
    prompt = "<|im_start|>user\nRespond with READY only.\n<|im_end|>\n<|im_start|>assistant\n"
    completion_payload = {
        "prompt": prompt,
        "n_predict": 1,
        "temperature": 0,
        "stop": ["<|im_end|>", "</s>", "<|endoftext|>"],
    }
    last_error = "LLM inference warm-up probe did not complete"

    while True:
        try:
            response = client.post(f"{base_url}/completion", json=completion_payload)
            if 200 <= response.status_code < 300:
                return
            if _is_loading_response(response):
                last_error = f"warming up ({response.status_code})"
            else:
                last_error = f"unexpected status {response.status_code}: {_response_body_text(response)[:200]}"
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        except httpx.ConnectError:
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"LLM inference readiness timed out after {max_wait_s:.0f}s at {base_url}/completion ({last_error})"
            )
        time.sleep(min(2.0, max(0.25, request_timeout_s / 10.0)))


def chat(
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 1200,
    *,
    timeout_s: float | None = None,
    max_attempts: int | None = None,
    stop: list[str] | None = None,
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
    - LLM_INFERENCE_READY_TIMEOUT_S: how long to wait for a tiny /completion warm-up probe
    """
    configured_url = settings.llm_base_url.rstrip("/")
    payload = {
        "model": settings.llm_model or "local-model",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    sanitized_stop = _sanitize_stop_sequences(stop)
    if sanitized_stop:
        payload["stop"] = sanitized_stop

    req_timeout_default = float(settings.llm_request_timeout_seconds)
    connect_timeout_default = float(settings.llm_connect_timeout_seconds)

    req_timeout = (
        float(timeout_s)
        if timeout_s is not None
        else _env_float("LLM_HTTP_TIMEOUT_S", req_timeout_default)
    )
    connect_timeout = _env_float("LLM_HTTP_CONNECT_TIMEOUT_S", connect_timeout_default)
    inference_ready_timeout = _env_float(
        "LLM_INFERENCE_READY_TIMEOUT_S",
        max(req_timeout, float(_env_int("LLM_READY_TIMEOUT_S", int(req_timeout_default))))
    )

    attempts = max(1, int(max_attempts)) if max_attempts is not None else max(1, _env_int("LLM_HTTP_MAX_ATTEMPTS", 2))
    backoff_s = _env_float("LLM_HTTP_RETRY_BACKOFF_S", 1.0)

    client_timeout = httpx.Timeout(req_timeout, connect=connect_timeout)

    last_exc: Exception | None = None
    base_urls = _candidate_base_urls(configured_url)
    for attempt in range(1, attempts + 1):
        for url in base_urls:
            endpoint = url + "/v1/chat/completions"
            try:
                with _build_http_client(client_timeout) as client:
                    _wait_for_inference_ready(
                        client,
                        url,
                        request_timeout_s=req_timeout,
                        max_wait_s=inference_ready_timeout,
                    )
                    r = client.post(endpoint, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    text = _extract_chat_text(data)
                    if text.strip():
                        return text

                    completion_payload = {
                        "prompt": _messages_to_prompt(messages),
                        "n_predict": max_tokens,
                        "temperature": temperature,
                        "stop": sanitized_stop or ["<|im_end|>", "</s>", "<|endoftext|>"],
                    }
                    r2 = client.post(url + "/completion", json=completion_payload)
                    r2.raise_for_status()
                    data2 = r2.json()
                    text2 = _normalize_generated_text(_extract_text(data2.get("content") or data2.get("text") or data2))
                    if text2.strip():
                        return text2

                    raise RuntimeError(
                        "LLM response contained no extractable text. "
                        f"chat_response={_response_preview(data)} completion_response={_response_preview(data2)}"
                    )
            except TimeoutError as e:
                last_exc = e
                continue
            except httpx.HTTPStatusError as e:
                last_exc = e
                if not _is_loading_response(e.response):
                    break
                continue
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as e:
                last_exc = e
                continue
            except Exception as e:
                last_exc = e
                continue
        if attempt >= attempts:
            break
        time.sleep(backoff_s * attempt)

    assert last_exc is not None
    raise last_exc
