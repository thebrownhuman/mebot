"""Admin CLI. Usage: python -m mebot.cli reset-password --email you@example.com"""

import argparse
import getpass
import sys

from mebot.auth import passwords
from mebot.config import Settings, ensure_data_dir
from mebot.db import make_session_factory, run_migrations
from mebot.repos import admin_sessions, admins


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mebot.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reset-password", help="set a new admin password (offline)")
    p.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    if args.command == "reset-password":
        return reset_password(args.email)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
