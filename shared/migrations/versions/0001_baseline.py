"""baseline: sessions and session_events, as create_all made them before migrations

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("repo_url", sa.String(), nullable=True),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("work_branch", sa.String(), nullable=True),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "session_events",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )


def downgrade():
    op.drop_table("session_events")
    op.drop_table("sessions")
