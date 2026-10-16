"""Pull request reviews: sessions.kind ("review" for a review's chat), pr_reviews (each review asked
for on GitHub, taken once) and auto_reviews (repos whose new pull requests Otto reviews by itself)

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="chat"))
    op.create_table(
        "pr_reviews",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("comment_id", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pr_reviews_user_id", "pr_reviews", ["user_id"])
    op.create_index("ix_pr_reviews_session_id", "pr_reviews", ["session_id"])
    op.create_table(
        "auto_reviews",
        sa.Column("repo_key", sa.String(), primary_key=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auto_reviews_user_id", "auto_reviews", ["user_id"])


def downgrade():
    op.drop_index("ix_auto_reviews_user_id", table_name="auto_reviews")
    op.drop_table("auto_reviews")
    op.drop_index("ix_pr_reviews_session_id", table_name="pr_reviews")
    op.drop_index("ix_pr_reviews_user_id", table_name="pr_reviews")
    op.drop_table("pr_reviews")
    with op.batch_alter_table("sessions") as b:
        b.drop_column("kind")
