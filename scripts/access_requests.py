"""List and approve access requests (POST /access-requests) while signups are invite-only.

    python -m scripts.access_requests              # pending requests, oldest first
    python -m scripts.access_requests --all        # approved ones too
    python -m scripts.access_requests approve 3    # by id, GitHub login or email

An approved request lets that GitHub login or email sign up (OTTO_SIGNUP_MODE=allowlist).
"""
import argparse, sys

from shared import access
from shared.db import init_db
from shared.models import as_utc


def _row(r) -> str:
    who = f"@{r.github_login}" if r.github_login else r.email
    note = " ".join(r.note.split())
    return f"{r.id:>5}  {as_utc(r.created_at):%Y-%m-%d %H:%M}  {r.status:<8}  {who}" + (f"  — {note}" if note else "")


def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m scripts.access_requests", description=__doc__.split("\n")[0])
    p.add_argument("--all", action="store_true", help="list approved requests too")
    sub = p.add_subparsers(dest="command")
    a = sub.add_parser("approve", help="approve a request")
    a.add_argument("who", help="the request's id, GitHub login or email")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "approve":
        row = access.find(args.who)
        if row is None:
            print(f"no access request for {args.who!r}", file=sys.stderr)
            return 1
        print(f"approved: {_row(access.approve(row.id))}")
        return 0
    rows = access.list_requests(None if args.all else "pending")
    for r in rows:
        print(_row(r))
    if not rows:
        print("no access requests" if args.all else "no pending access requests")
    return 0


if __name__ == "__main__":
    init_db()
    sys.exit(main())
