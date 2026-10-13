"""session_events.client_message_id: the id a client sent with a message, so posting it again
stores nothing (unique per session; NULL for every other event)

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("session_events", sa.Column("client_message_id", sa.String(), nullable=True))
    op.create_index("ix_session_events_client_message_id", "session_events", ["session_id", "client_message_id"],
                    unique=True)


def downgrade():
    op.drop_index("ix_session_events_client_message_id", table_name="session_events")
    op.drop_column("session_events", "client_message_id")
