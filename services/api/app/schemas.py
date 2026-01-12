from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from uuid import UUID
from datetime import datetime

class SessionPreferences(BaseModel):
    units: Literal["mm","inch"] = "mm"
    tolerance_mm: float = 0.2
    manufacturing_profile: Literal["fdm_3d_print","sla_3d_print","cnc_basic"] = "fdm_3d_print"
    require_citations: bool = True
    require_freecad_validation: bool = True

class CreateSessionRequest(BaseModel):
    title: Optional[str]=None
    project_id: Optional[str]=None
    preferences: Optional[SessionPreferences]=None

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
    client_request_id: Optional[str]=None
    mode: Literal["design","modify","explain","export"]="design"

class MessageOut(BaseModel):
    message_id: UUID
    role: Literal["user","assistant","tool"]
    content: str
    created_at: datetime

class ArtifactOut(BaseModel):
    artifact_id: UUID
    kind: str
    path: str
    created_at: datetime
    sha256: Optional[str]=None
    bytes: Optional[int]=None

class CitationOut(BaseModel):
    source_id: str
    chunk_id: str
    locator: str
    quote: Optional[str]=None

class ValidationSummary(BaseModel):
    status: Literal["passed","failed","skipped"]
    iterations: int = 0
    issues: list[str] = Field(default_factory=list)

class CreateMessageResponse(BaseModel):
    session_id: UUID
    message_id: UUID
    assistant_message: MessageOut
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    validation: ValidationSummary

class LogEventOut(BaseModel):
    event_id: UUID
    session_id: UUID
    ts: datetime
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)

class LogEventList(BaseModel):
    events: list[LogEventOut]

class SessionMetrics(BaseModel):
    session_id: UUID
    prompts: int
    completions: int
    validations: int

class SourceOut(BaseModel):
    source_id: str
    enabled: bool
    blacklisted: bool
    trust_tier: int
    kind: str
    entrypoints: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    license_note: str | None = None

class SourceList(BaseModel):
    sources: list[SourceOut]

class ReconcileResult(BaseModel):
    added: list[str]
    updated: list[str]
    disabled: list[str]
