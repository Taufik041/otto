"""provider_health: providers or models the brain found unusable (quota, auth, model), for
GET /models; the gateway clears it when it starts

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_health",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("provider_health")
