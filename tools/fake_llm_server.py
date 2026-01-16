from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import time


app = FastAPI(title="Fake LLM", version="0.1.0")


@app.get("/")
def root():
    return {"ok": True, "service": "fake-llm"}


@app.get("/health")
def health():
    return {"ok": True}


class ChatCompletionMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatCompletionMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest) -> Dict[str, Any]:
    # Minimal OpenAI-compatible response. We don't attempt to be smart here;
    # the goal is to unblock integration tests without a heavy model.
    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    content = (
        "# Fake LLM Response\n\n"
        "This is a stubbed LLM used for the 'test' docker compose profile.\n\n"
        f"Echo: {last_user[:200]}"
    )
    now = int(time.time())
    return {
        "id": "chatcmpl_fake",
        "object": "chat.completion",
        "created": now,
        "model": req.model or "fake",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
