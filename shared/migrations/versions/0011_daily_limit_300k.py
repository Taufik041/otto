"""the default daily token limit is now 300,000: users still on the old default (50,000) move up;
limits set to anything else stay

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

OLD, NEW = 50_000, 300_000


def upgrade():
    op.execute(sa.text("UPDATE users SET daily_token_limit = :new WHERE daily_token_limit = :old")
               .bindparams(new=NEW, old=OLD))


def downgrade():
    # data only: who was on the old default can't be told apart from who chose 300,000, so the
    # limits stay as they are
    pass
