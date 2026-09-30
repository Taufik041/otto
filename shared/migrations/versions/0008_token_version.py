"""users.token_version: login tokens carry it; bumping it (a password change or reset) signs out
every device

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_column("token_version")
