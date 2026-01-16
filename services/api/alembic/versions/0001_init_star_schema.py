"""init star schema

Revision ID: 0001_init
Revises:
Create Date: 2026-01-11
"""
from pgvector.sqlalchemy import Vector
from alembic import op
import sqlalchemy as sa


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.create_table(
        "dim_time",
        sa.Column("time_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, unique=True),
    )

    op.create_table(
        "dim_user",
        sa.Column("user_id", sa.String, primary_key=True),
        sa.Column("display_name", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False),
    )
    op.execute("INSERT INTO dim_user (user_id, display_name, role) VALUES ('local','local','owner')")

    op.create_table(
        "dim_model",
        sa.Column("model_id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("version", sa.String, nullable=False),
        sa.Column("quantization", sa.String, nullable=False),
        sa.Column("context_length", sa.Integer, nullable=False),
        sa.Column("backend", sa.String, nullable=False),
        sa.Column("device", sa.String, nullable=False),
    )
    op.execute("""
      INSERT INTO dim_model (model_id, name, version, quantization, context_length, backend, device)
      VALUES ('cpu-default','local-llm','0','unknown',4096,'llama.cpp','cpu')
    """)

    op.create_table(
        "dim_session",
        sa.Column("session_id", sa.String, primary_key=True),
        sa.Column("parent_session_id", sa.String, nullable=True),
        sa.Column("project_id", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preferences_json", sa.JSON, nullable=False),
        sa.Column("latest_state_json", sa.JSON, nullable=False),
    )

    op.create_table(
        "dim_source",
        sa.Column("source_id", sa.String, primary_key=True),
        sa.Column("domain", sa.String, nullable=True),
        sa.Column("trust_tier", sa.Integer, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False),
        sa.Column("is_blacklisted", sa.Boolean, nullable=False),
        sa.Column("entrypoints_json", sa.JSON, nullable=False),
        sa.Column("include_patterns_json", sa.JSON, nullable=False),
        sa.Column("exclude_patterns_json", sa.JSON, nullable=False),
        sa.Column("license_note", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "dim_artifact",
        sa.Column("artifact_id", sa.String, primary_key=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("storage_provider", sa.String, nullable=False),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("sha256", sa.String, nullable=True),
        sa.Column("bytes", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table("rag_documents",
        sa.Column("doc_id", sa.String, primary_key=True),
        sa.Column("source_id", sa.String, sa.ForeignKey("dim_source.source_id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String, nullable=True),
        sa.Column("license_note", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=False),
    )
    op.create_table("rag_chunks",
        sa.Column("chunk_id", sa.String, primary_key=True),
        sa.Column("doc_id", sa.String, sa.ForeignKey("rag_documents.doc_id"), nullable=False),
        sa.Column("source_id", sa.String, sa.ForeignKey("dim_source.source_id"), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("locator", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding ON rag_chunks USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);")
    op.create_table("log_events",
        sa.Column("event_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False),
    )

    op.create_table(
        "fact_prompt",
        sa.Column("prompt_fact_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False, index=True),
        sa.Column("user_id", sa.String, sa.ForeignKey("dim_user.user_id"), nullable=False),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("message_id", sa.String, nullable=False, index=True),
        sa.Column("mode", sa.String, nullable=False),
        sa.Column("prompt_chars", sa.Integer, nullable=False),
    )

    op.create_table(
        "fact_completion",
        sa.Column("completion_fact_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False, index=True),
        sa.Column("model_id", sa.String, sa.ForeignKey("dim_model.model_id"), nullable=False),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("message_id", sa.String, nullable=False, index=True),
        sa.Column("output_chars", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("repair_iterations", sa.Integer, nullable=False),
    )

    op.create_table(
        "fact_validation_result",
        sa.Column("validation_fact_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False, index=True),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("message_id", sa.String, nullable=False, index=True),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("iteration_index", sa.Integer, nullable=False),
        sa.Column("issues_count", sa.Integer, nullable=False),
    )

    op.create_table(
        "fact_citation",
        sa.Column("citation_fact_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False, index=True),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("message_id", sa.String, nullable=False, index=True),
        sa.Column("source_id", sa.String, sa.ForeignKey("dim_source.source_id"), nullable=False),
        sa.Column("chunk_id", sa.String, nullable=False),
        sa.Column("locator", sa.Text, nullable=False),
    )

    op.create_table(
        "fact_artifact_event",
        sa.Column("artifact_event_id", sa.String, primary_key=True),
        sa.Column("artifact_id", sa.String, sa.ForeignKey("dim_artifact.artifact_id"), nullable=False),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False, index=True),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("message_id", sa.String, nullable=False, index=True),
        sa.Column("event_type", sa.String, nullable=False),
    )

    op.create_table(
        "fact_source_change",
        sa.Column("source_change_fact_id", sa.String, primary_key=True),
        sa.Column("source_id", sa.String, sa.ForeignKey("dim_source.source_id"), nullable=False),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("change_type", sa.String, nullable=False),
        sa.Column("actor_user_id", sa.String, sa.ForeignKey("dim_user.user_id"), nullable=False),
        sa.Column("config_hash", sa.String, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("log_events")
    op.drop_table("fact_source_change")
    op.drop_table("fact_artifact_event")
    op.drop_table("fact_citation")
    op.drop_table("fact_validation_result")
    op.drop_table("fact_completion")
    op.drop_table("fact_prompt")
    op.drop_table("dim_artifact")
    op.drop_table("dim_source")
    op.drop_table("dim_session")
    op.drop_table("dim_model")
    op.drop_table("dim_user")
    op.drop_table("dim_time")
    op.drop_table("rag_chunks")
    op.drop_table("rag_documents")
