"""sessions.client_message_id: the first message's id from the client, unique per user, so posting
a new chat again (a retry, a double click) returns the first one

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("client_message_id", sa.String(), nullable=True))
        b.create_index("ix_sessions_client_message_id", ["user_id", "client_message_id"], unique=True)


def downgrade():
    with op.batch_alter_table("sessions") as b:
        b.drop_index("ix_sessions_client_message_id")
        b.drop_column("client_message_id")
