"""Accounts, for requests sent to support@taufi.dev.

    python -m scripts.accounts delete taufik@example.com   # by email
    python -m scripts.accounts delete Taufik041            # or by GitHub login (an @ is fine)

delete does what Settings → Account → "Delete account" does: the account is deactivated at once
(signed out everywhere, its sessions and sandboxes stopped, GitHub dropped, its email and GitHub
login free to sign up again), "Your Otto account has been deleted" is emailed, and its data is
purged within 30 days. Run it where the gateway runs: it needs the database and the bus.
"""
import argparse, asyncio, sys

from gateway import app as gateway_app
from shared import config
from shared.accounts import find_account
from shared.db import init_db


def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m scripts.accounts", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("delete", help="delete an account, as Settings does")
    d.add_argument("who", help="the account's email or GitHub login")
    return p.parse_args(argv)


async def _delete(user_id) -> bool:
    conn = await gateway_app.connect_robust(config.BUS_URL)  # its sandboxes' queues are on the bus
    try:
        return await gateway_app.close_account(await conn.channel(), user_id)
    finally:
        await conn.close()


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    user = find_account(args.who)
    if user is None:
        print(f"no account with the email or GitHub login {args.who!r}", file=sys.stderr)
        return 1
    if not asyncio.run(_delete(user.id)):
        print(f"account {user.id} was deleted meanwhile", file=sys.stderr)
        return 1
    print(f"deleted account {user.id} ({args.who}): signed out everywhere, its data is purged within 30 days")
    return 0


if __name__ == "__main__":
    init_db()
    sys.exit(main())
