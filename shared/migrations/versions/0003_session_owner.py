"""sessions belong to a user

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # nullable: sessions made by the brain CLI (and any from before accounts) have no owner,
    # so no user sees them through the API
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("user_id", sa.String(), nullable=True))
        b.create_foreign_key("fk_sessions_user_id_users", "users", ["user_id"], ["id"])
        b.create_index("ix_sessions_user_id", ["user_id"])


def downgrade():
    with op.batch_alter_table("sessions") as b:
        b.drop_index("ix_sessions_user_id")
        b.drop_constraint("fk_sessions_user_id_users", type_="foreignkey")
        b.drop_column("user_id")
