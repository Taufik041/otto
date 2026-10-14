"""users.deleted_at, purge_keys and purged_at: a deleted account is deactivated at once (its email
and GitHub login freed) and purged later; purge_keys holds only hashes of the email and GitHub
login it had, so the purge can find its access requests

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("purge_keys", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True))
        b.add_column(sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_column("purged_at")
        b.drop_column("purge_keys")
        b.drop_column("deleted_at")
