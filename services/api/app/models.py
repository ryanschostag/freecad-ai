import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from pgvector.sqlalchemy import Vector

def _uuid(): return str(uuid.uuid4())

class DimTime(Base):
    __tablename__="dim_time"
    time_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, unique=True)

class DimSession(Base):
    __tablename__="dim_session"
    session_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    parent_session_id: Mapped[str|None] = mapped_column(String, nullable=True)
    project_id: Mapped[str|None] = mapped_column(String, nullable=True)
    title: Mapped[str|None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    closed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    preferences_json: Mapped[dict] = mapped_column(JSON, default=dict)
    latest_state_json: Mapped[dict] = mapped_column(JSON, default=dict)

class DimUser(Base):
    __tablename__="dim_user"
    user_id: Mapped[str] = mapped_column(String, primary_key=True, default="local")
    display_name: Mapped[str] = mapped_column(String, default="local")
    role: Mapped[str] = mapped_column(String, default="owner")

class DimModel(Base):
    __tablename__="dim_model"
    model_id: Mapped[str] = mapped_column(String, primary_key=True, default="cpu-default")
    name: Mapped[str] = mapped_column(String, default="local-llm")
    version: Mapped[str] = mapped_column(String, default="0")
    quantization: Mapped[str] = mapped_column(String, default="unknown")
    context_length: Mapped[int] = mapped_column(Integer, default=4096)
    backend: Mapped[str] = mapped_column(String, default="llama.cpp")
    device: Mapped[str] = mapped_column(String, default="cpu")

class DimSource(Base):
    __tablename__="dim_source"
    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    domain: Mapped[str|None] = mapped_column(String, nullable=True)
    trust_tier: Mapped[int] = mapped_column(Integer, default=2)
    kind: Mapped[str] = mapped_column(String, default="crawl")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    entrypoints_json: Mapped[list] = mapped_column(JSON, default=list)
    include_patterns_json: Mapped[list] = mapped_column(JSON, default=list)
    exclude_patterns_json: Mapped[list] = mapped_column(JSON, default=list)
    license_note: Mapped[str|None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class DimArtifact(Base):
    __tablename__="dim_artifact"
    artifact_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String)
    storage_provider: Mapped[str] = mapped_column(String, default="minio")
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str|None] = mapped_column(String, nullable=True)
    bytes: Mapped[int|None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class RagDocument(Base):
    __tablename__="rag_documents"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str|None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    content_hash: Mapped[str|None] = mapped_column(String, nullable=True)
    license_note: Mapped[str|None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

class RagChunk(Base):
    __tablename__="rag_chunks"
    chunk_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("rag_documents.doc_id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    locator: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(Vector(384))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

class FactPrompt(Base):
    __tablename__="fact_prompt"
    prompt_fact_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("dim_session.session_id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("dim_user.user_id"), default="local")
    time_id: Mapped[int|None] = mapped_column(ForeignKey("dim_time.time_id"), nullable=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String, default="design")
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0)

class FactCompletion(Base):
    __tablename__="fact_completion"
    completion_fact_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("dim_session.session_id"), index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("dim_model.model_id"), default="cpu-default")
    time_id: Mapped[int|None] = mapped_column(ForeignKey("dim_time.time_id"), nullable=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int|None] = mapped_column(Integer, nullable=True)
    repair_iterations: Mapped[int] = mapped_column(Integer, default=0)

class FactValidationResult(Base):
    __tablename__="fact_validation_result"
    validation_fact_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("dim_session.session_id"), index=True)
    time_id: Mapped[int|None] = mapped_column(ForeignKey("dim_time.time_id"), nullable=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    iteration_index: Mapped[int] = mapped_column(Integer, default=0)
    issues_count: Mapped[int] = mapped_column(Integer, default=0)

class FactArtifactEvent(Base):
    __tablename__="fact_artifact_event"
    artifact_event_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("dim_artifact.artifact_id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("dim_session.session_id"), index=True)
    time_id: Mapped[int|None] = mapped_column(ForeignKey("dim_time.time_id"), nullable=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, default="created")

class FactSourceChange(Base):
    __tablename__="fact_source_change"
    source_change_fact_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("dim_source.source_id"))
    time_id: Mapped[int|None] = mapped_column(ForeignKey("dim_time.time_id"), nullable=True)
    change_type: Mapped[str] = mapped_column(String)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("dim_user.user_id"), default="local")
    config_hash: Mapped[str|None] = mapped_column(String, nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)

class LogEvent(Base):
    __tablename__="log_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("dim_session.session_id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    type: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)


class DimValidationRule(Base):
    __tablename__="dim_validation_rule"
    rule_code: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String, default="general")
    severity: Mapped[str] = mapped_column(String, default="error")  # info|warning|error
    description: Mapped[str] = mapped_column(Text, default="")

class FactValidationIssue(Base):
    __tablename__="fact_validation_issue"
    validation_issue_fact_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    validation_fact_id: Mapped[str] = mapped_column(ForeignKey("fact_validation_result.validation_fact_id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("dim_session.session_id"), index=True)
    time_id: Mapped[int|None] = mapped_column(ForeignKey("dim_time.time_id"), nullable=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    rule_code: Mapped[str] = mapped_column(ForeignKey("dim_validation_rule.rule_code"))
    object_name: Mapped[str|None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
