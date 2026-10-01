"""installations: the GitHub App installations each user connected

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "installations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_login", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_installations_user_id", "installations", ["user_id"])


def downgrade():
    op.drop_index("ix_installations_user_id", "installations")
    op.drop_table("installations")
