"""usage outlives its session: deleting a chat keeps its tokens (session_id becomes NULL)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usage") as b:
        b.alter_column("session_id", existing_type=sa.String(), nullable=True)


def downgrade():
    op.execute("DELETE FROM usage WHERE session_id IS NULL")
    with op.batch_alter_table("usage") as b:
        b.alter_column("session_id", existing_type=sa.String(), nullable=False)
