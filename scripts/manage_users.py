"""
User administration CLI for the IPM Tool.

Usage (from the project root):
    python scripts/manage_users.py add <username> --role admin [--password ...]
    python scripts/manage_users.py reset-password <username> [--password ...]
    python scripts/manage_users.py set-role <username> analyst|admin
    python scripts/manage_users.py disable <username>
    python scripts/manage_users.py enable <username>
    python scripts/manage_users.py list

If --password is omitted, you are prompted (input hidden). Passwords are stored as
Argon2id hashes; the plaintext is never persisted or logged.
"""

import argparse
import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.auth.security import hash_password  # noqa: E402
from backend.db.engine import get_session  # noqa: E402
from backend.db.models import User  # noqa: E402

ROLES = ("admin", "analyst")


def _get(session, username):
    return session.query(User).filter(User.username == username).one_or_none()


def _prompt_password() -> str:
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Confirm password: "):
        sys.exit("Passwords did not match.")
    if len(pw) < 8:
        sys.exit("Password must be at least 8 characters.")
    return pw


def cmd_add(args):
    with get_session() as s:
        if _get(s, args.username):
            sys.exit(f"User {args.username!r} already exists.")
        pw = args.password or _prompt_password()
        s.add(User(username=args.username, password_hash=hash_password(pw), role=args.role))
    print(f"Created user {args.username!r} (role={args.role}).")


def cmd_reset_password(args):
    with get_session() as s:
        u = _get(s, args.username)
        if not u:
            sys.exit(f"No such user: {args.username!r}")
        u.password_hash = hash_password(args.password or _prompt_password())
    print(f"Password reset for {args.username!r}.")


def cmd_set_role(args):
    with get_session() as s:
        u = _get(s, args.username)
        if not u:
            sys.exit(f"No such user: {args.username!r}")
        u.role = args.role
    print(f"{args.username!r} role set to {args.role}.")


def _set_active(username, active):
    with get_session() as s:
        u = _get(s, username)
        if not u:
            sys.exit(f"No such user: {username!r}")
        u.is_active = active
    print(f"{username!r} {'enabled' if active else 'disabled'}.")


def cmd_list(_args):
    with get_session() as s:
        users = s.query(User).order_by(User.username).all()
        if not users:
            print("No users yet.")
            return
        print(f"{'USERNAME':<24} {'ROLE':<10} {'ACTIVE':<7} LAST LOGIN")
        for u in users:
            last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "never"
            print(f"{u.username:<24} {u.role:<10} {'yes' if u.is_active else 'no':<7} {last}")


def build_parser():
    p = argparse.ArgumentParser(description="IPM Tool user management")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="create a user")
    a.add_argument("username")
    a.add_argument("--role", choices=ROLES, default="analyst")
    a.add_argument("--password")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("reset-password", help="reset a user's password")
    r.add_argument("username")
    r.add_argument("--password")
    r.set_defaults(func=cmd_reset_password)

    sr = sub.add_parser("set-role", help="change a user's role")
    sr.add_argument("username")
    sr.add_argument("role", choices=ROLES)
    sr.set_defaults(func=cmd_set_role)

    d = sub.add_parser("disable", help="deactivate a user")
    d.add_argument("username")
    d.set_defaults(func=lambda args: _set_active(args.username, False))

    e = sub.add_parser("enable", help="reactivate a user")
    e.add_argument("username")
    e.set_defaults(func=lambda args: _set_active(args.username, True))

    ls = sub.add_parser("list", help="list users")
    ls.set_defaults(func=cmd_list)

    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
