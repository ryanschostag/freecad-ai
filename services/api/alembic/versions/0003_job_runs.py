"""persist jobs in postgres

Revision ID: 0003_job_runs
Revises: 0002_validation_taxonomy
Create Date: 2026-01-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_job_runs"
down_revision = "0002_validation_taxonomy"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "job_runs",
        sa.Column("job_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False),
        sa.Column("user_message_id", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.JSON, nullable=False),
        sa.Column("error_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_job_runs_session_id", "job_runs", ["session_id"])
    op.create_index("ix_job_runs_user_message_id", "job_runs", ["user_message_id"])

def downgrade():
    op.drop_index("ix_job_runs_user_message_id", table_name="job_runs")
    op.drop_index("ix_job_runs_session_id", table_name="job_runs")
    op.drop_table("job_runs")
