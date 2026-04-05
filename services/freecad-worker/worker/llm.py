from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

from worker.settings import settings
from worker.model_state import load_latest_snapshot


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
    if not s:
        return s

    # Handle the common case where the model starts with a fenced code block,
    # including incomplete or truncated responses that start with a markdown fence
    # emit the closing fence before generation stops.
    if s.startswith("```"):
        s = re.sub(r"^```[\t ]*[A-Za-z0-9_+-]*\r?\n?", "", s, count=1)
        s = s.strip()

    # Remove a trailing closing fence even when the opening fence was already
    # stripped or the model emitted only the closing delimiter.
    s = re.sub(r"\r?\n```\s*$", "", s).strip()
    if s == "```":
        return ""
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




def _inject_persisted_training_profile(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    snapshot = load_latest_snapshot(settings.llm_state_dir)
    if snapshot is None or not snapshot.inference_profile:
        return messages

    profile = snapshot.inference_profile
    parts: list[str] = []
    system_message = str(profile.get("system_message") or "").strip()
    if system_message:
        parts.append(system_message)

    examples = profile.get("examples") or []
    if isinstance(examples, list) and examples:
        rendered_examples: list[str] = []
        for item in examples[:3]:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt") or "").strip()
            response = str(item.get("response") or "").strip()
            if prompt and response:
                rendered_examples.append(f"Example user request: {prompt}\nExample assistant response pattern: {response}")
        if rendered_examples:
            parts.append("Persisted training examples:\n" + "\n\n".join(rendered_examples))

    snippets = profile.get("retrieval_snippets") or []
    if isinstance(snippets, list) and snippets:
        excerpt = [str(item).strip() for item in snippets[:2] if str(item).strip()]
        if excerpt:
            parts.append("Persisted retrieval snippets:\n" + "\n---\n".join(excerpt))

    if not parts:
        return messages

    injected = {"role": "system", "content": "\n\n".join(parts)}
    if messages and messages[0].get("role") == "system":
        merged = dict(messages[0])
        merged["content"] = f"{injected['content']}\n\n{messages[0].get('content', '')}".strip()
        return [merged, *messages[1:]]
    return [injected, *messages]

def chat(
    messages: list[dict[str, str]],
    temperature: float = 0.1,
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
    """
    url = settings.llm_base_url.rstrip("/")
    endpoint = url + "/v1/chat/completions"
    effective_messages = _inject_persisted_training_profile(messages)
    payload = {
        "model": settings.llm_model or "local-model",
        "messages": effective_messages,
        "temperature": temperature,
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

    attempts = max(1, int(max_attempts)) if max_attempts is not None else max(1, _env_int("LLM_HTTP_MAX_ATTEMPTS", 2))
    backoff_s = _env_float("LLM_HTTP_RETRY_BACKOFF_S", 1.0)

    client_timeout = httpx.Timeout(req_timeout, connect=connect_timeout)

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=client_timeout) as client:
                r = client.post(endpoint, json=payload)
                r.raise_for_status()
                data = r.json()
                text = _extract_chat_text(data)
                if text.strip():
                    return text

                # llama.cpp can still produce a valid completion while returning a non-string
                # or otherwise unusual OpenAI-compatible payload shape. Fall back to the native
                # /completion endpoint before declaring the response empty.
                completion_payload = {
                    "prompt": _messages_to_prompt(effective_messages),
                    "n_predict": -1,
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
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_exc = e
            if attempt >= attempts:
                raise
            time.sleep(backoff_s * attempt)
        except Exception as e:
            last_exc = e
            if attempt >= attempts:
                raise
            time.sleep(backoff_s * attempt)

    assert last_exc is not None
    raise last_exc
