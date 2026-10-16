"""CI awareness: sessions.head_sha (the commit Otto pushed last, which CI results map to) and
webhook_deliveries (GitHub's X-GitHub-Delivery ids, so a redelivery is taken in once)

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("head_sha", sa.String(), nullable=True))
        b.create_index("ix_sessions_head_sha", ["head_sha"])
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhook_deliveries_received_at", "webhook_deliveries", ["received_at"])


def downgrade():
    op.drop_index("ix_webhook_deliveries_received_at", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    with op.batch_alter_table("sessions") as b:
        b.drop_index("ix_sessions_head_sha")
        b.drop_column("head_sha")
