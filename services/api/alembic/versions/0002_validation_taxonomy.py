"""validation taxonomy

Revision ID: 0002_validation_taxonomy
Revises: 0001_init
Create Date: 2026-01-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_validation_taxonomy"
down_revision = "0001_init"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "dim_validation_rule",
        sa.Column("rule_code", sa.String, primary_key=True),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
    )
    op.create_table(
        "fact_validation_issue",
        sa.Column("validation_issue_fact_id", sa.String, primary_key=True),
        sa.Column("validation_fact_id", sa.String, sa.ForeignKey("fact_validation_result.validation_fact_id"), nullable=False),
        sa.Column("session_id", sa.String, sa.ForeignKey("dim_session.session_id"), nullable=False),
        sa.Column("time_id", sa.Integer, sa.ForeignKey("dim_time.time_id"), nullable=True),
        sa.Column("message_id", sa.String, nullable=False),
        sa.Column("rule_code", sa.String, sa.ForeignKey("dim_validation_rule.rule_code"), nullable=False),
        sa.Column("object_name", sa.String, nullable=True),
        sa.Column("message", sa.Text, nullable=False),
    )

    # Seed a starter taxonomy
    rules = [
      ("CONSTRAINT_OVERCONSTRAINED","constraints","error","Sketch has conflicting constraints (over-constrained)."),
      ("CONSTRAINT_UNDERCONSTRAINED","constraints","warning","Sketch is under-constrained."),
      ("CONSTRAINT_REDUNDANT","constraints","warning","Redundant constraints detected."),
      ("FREECAD_EXCEPTION","runtime","error","FreeCAD threw an exception or exited non-zero."),
      ("FREECAD_NOT_INSTALLED","runtime","error","freecadcmd not found in worker image."),
      ("EXPORT_FAILED","export","error","One or more exports (FCStd/STEP/STL) failed."),
    ]
    for rc, cat, sev, desc in rules:
        op.execute(
            sa.text("INSERT INTO dim_validation_rule (rule_code, category, severity, description) VALUES (:rc,:cat,:sev,:desc)")
            .bindparams(rc=rc, cat=cat, sev=sev, desc=desc)
        )

def downgrade():
    op.drop_table("fact_validation_issue")
    op.drop_table("dim_validation_rule")
