"""email_verifications: "Confirm your email" links. Accounts from before this that have a
password, or GitHub, count as verified, so nobody is locked out.

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_verifications",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_verifications_user_id", "email_verifications", ["user_id"])
    op.execute("UPDATE users SET email_verified = true WHERE email IS NOT NULL "
               "AND (password_hash IS NOT NULL OR github_id IS NOT NULL)")


def downgrade():
    op.drop_index("ix_email_verifications_user_id", "email_verifications")
    op.drop_table("email_verifications")
