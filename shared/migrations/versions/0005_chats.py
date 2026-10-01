"""chats: sessions get a title and an optional repo ("owner/name"); repo_url is derived from it

Revision ID: 0005
Revises: 0004
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

REPO_URL = re.compile(r"github\.com[/:]([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$")
sessions = sa.table("sessions", sa.column("id", sa.String), sa.column("task", sa.String),
                    sa.column("title", sa.String), sa.column("repo", sa.String), sa.column("repo_url", sa.String))


def upgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("title", sa.String(), nullable=True))
        b.add_column(sa.Column("repo", sa.String(), nullable=True))
    conn = op.get_bind()
    for sid, task, url in conn.execute(sa.select(sessions.c.id, sessions.c.task, sessions.c.repo_url)).all():
        m = REPO_URL.search(url or "")
        conn.execute(sessions.update().where(sessions.c.id == sid).values(
            title=" ".join(task.split())[:60].rstrip() or "New chat", repo=m.group(1) if m else None))
    with op.batch_alter_table("sessions") as b:
        b.alter_column("title", existing_type=sa.String(), nullable=False)
        b.drop_column("repo_url")


def downgrade():
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("repo_url", sa.String(), nullable=True))
    conn = op.get_bind()
    for sid, repo in conn.execute(sa.select(sessions.c.id, sessions.c.repo)).all():
        if repo:
            conn.execute(sessions.update().where(sessions.c.id == sid)
                         .values(repo_url=f"https://github.com/{repo}"))
    with op.batch_alter_table("sessions") as b:
        b.drop_column("repo")
        b.drop_column("title")
