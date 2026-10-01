"""refresh_tokens.revoked_reason: rotated, logout, reuse, password or logout_all; a token rotated
moments ago may be retried, unless its family was ended for another reason

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("refresh_tokens") as b:
        b.add_column(sa.Column("revoked_reason", sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table("refresh_tokens") as b:
        b.drop_column("revoked_reason")
