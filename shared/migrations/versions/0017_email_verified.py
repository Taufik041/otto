"""users.email_verified: the email is one its owner proved they have (GitHub's verified primary
email, for an account made by GitHub sign-in); false for every account before this

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_column("email_verified")
