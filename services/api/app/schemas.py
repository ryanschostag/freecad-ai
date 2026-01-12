from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from uuid import UUID
from datetime import datetime

class CreateSessionRequest(BaseModel):
    title: Optional[str]=None
    project_id: Optional[str]=None

class SessionOut(BaseModel):
    session_id: UUID
    parent_session_id: Optional[UUID]=None
    project_id: Optional[str]=None
    title: Optional[str]=None
    status: Literal["active","closed"]
    created_at: datetime
    closed_at: Optional[datetime]=None

class CreateMessageRequest(BaseModel):
    content: str
    mode: Literal["design","modify","explain","export"]="design"

class MessageOut(BaseModel):
    message_id: UUID
    role: Literal["user","assistant","tool"]
    content: str
    created_at: datetime

class ArtifactOut(BaseModel):
    artifact_id: UUID
    kind: str
    object_key: str
    created_at: datetime
    sha256: Optional[str]=None
    bytes: Optional[int]=None

class ValidationSummary(BaseModel):
    status: Literal["passed","failed","skipped"]
    iterations: int = 0
    issues: list[str] = Field(default_factory=list)

class CreateMessageResponse(BaseModel):
    session_id: UUID
    message_id: UUID
    assistant_message: MessageOut
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    validation: ValidationSummary

class LogEventOut(BaseModel):
    event_id: UUID
    session_id: UUID
    ts: datetime
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)

class LogEventList(BaseModel):
    events: list[LogEventOut]

class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 8
    max_trust_tier: int = 2

class RagResult(BaseModel):
    chunk_id: UUID
    source_id: str
    locator: str
    score: float
    text: str

class RagQueryResponse(BaseModel):
    results: list[RagResult] = Field(default_factory=list)
