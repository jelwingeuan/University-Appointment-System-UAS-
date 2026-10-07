"""Index newest-first audit log pagination.

Revision ID: 0003_audit_log_ordering
Revises: 0002_production_foundation
"""

from alembic import op

revision = "0003_audit_log_ordering"
down_revision = "0002_production_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_audit_logs_created_id", "audit_logs", ["created_at", "id"])


def downgrade():
    op.drop_index("ix_audit_logs_created_id", table_name="audit_logs")
