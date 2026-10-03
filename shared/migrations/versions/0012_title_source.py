"""sessions.title_source: auto (from the first message), generated (the PR's or the model's title)
or user (renamed, never replaced)

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("title_source", sa.String(), nullable=False, server_default="auto"))


def downgrade():
    with op.batch_alter_table("sessions") as b:
        b.drop_column("title_source")
