"""Admin CLI.

  python -m mebot.cli reset-password --email you@example.com
  python -m mebot.cli invite create [--note TEXT] [--days N]   (hosted, SIGNUP_MODE=invite)
"""

import argparse
import getpass
import sys

from mebot.auth import passwords
from mebot.config import Settings, ensure_data_dir
from mebot.db import make_session_factory, run_migrations
from mebot.repos import admin_sessions, admins, invites


def _err(msg: str) -> int:
    print(f"mebot: {msg}", file=sys.stderr)
    return 1


def reset_password(email: str) -> int:
    settings = Settings()
    ensure_data_dir(settings)
    run_migrations(settings.database_url)
    with make_session_factory(settings.database_url)() as db:
        admin = admins.get_by_email(db, email)
        if admin is None:
            return _err(f"no admin with email {email!r}")
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat new password: "):
            return _err("passwords do not match")
        if not passwords.MIN_LENGTH <= len(pw) <= passwords.MAX_LENGTH:
            return _err(
                f"password must be {passwords.MIN_LENGTH}-{passwords.MAX_LENGTH} characters"
            )
        admins.set_password_hash(db, admin, passwords.hash_password(pw))
        db.commit()
        admin_sessions.revoke_all(db, admin.id)
    print(f"Password for {admin.email} reset; all sessions signed out.")
    return 0


def create_invite(note: str | None, days: int) -> int:
    settings = Settings()
    if not settings.hosted:
        return _err("invites are for MODE=hosted")
    ensure_data_dir(settings)
    run_migrations(settings.database_url, settings.secret_key)
    with make_session_factory(settings.database_url)() as db:
        code = invites.create(db, note=note, days=days or None)
        db.commit()
    expiry = f"valid {days} days" if days else "never expires"
    print(f"Invite code ({expiry}, single use): {code}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mebot.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reset-password", help="set a new admin password (offline)")
    p.add_argument("--email", required=True)
    inv = sub.add_parser("invite", help="invite codes for hosted sign-up")
    inv_sub = inv.add_subparsers(dest="action", required=True)
    ic = inv_sub.add_parser("create", help="print a new single-use invite code")
    ic.add_argument("--note")
    ic.add_argument("--days", type=int, default=30, help="0 = never expires")
    args = parser.parse_args(argv)
    if args.command == "reset-password":
        return reset_password(args.email)
    if args.command == "invite":
        return create_invite(args.note, args.days)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
