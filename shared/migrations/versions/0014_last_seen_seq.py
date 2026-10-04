"""sessions.last_seen_seq: the last event the user saw in the chat, for the sidebar's unread dot

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("last_seen_seq", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("sessions") as b:
        b.drop_column("last_seen_seq")
