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


def create_platform_admin(email: str) -> int:
    from mebot.hosted import operator

    settings = Settings()
    if not settings.hosted:
        return _err("the platform operator exists only with MODE=hosted")
    ensure_data_dir(settings)
    run_migrations(settings.database_url, settings.secret_key)
    with make_session_factory(settings.database_url)() as db:
        if operator.get_by_email(db, email) is not None:
            return _err(f"operator {email!r} already exists")
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat password: "):
            return _err("passwords do not match")
        if not passwords.MIN_LENGTH <= len(pw) <= passwords.MAX_LENGTH:
            return _err(
                f"password must be {passwords.MIN_LENGTH}-{passwords.MAX_LENGTH} characters"
            )
        operator.create_admin(db, email, passwords.hash_password(pw))
        db.commit()
    print(f"Operator {email.strip().lower()} created. Log in at /platform.")
    return 0


def plans_cmd(args) -> int:
    """Paid plans: list, set a price per currency, set a limit (hosted only)."""
    import json

    from mebot.billing import service
    from mebot.models import Plan, utcnow

    settings = Settings()
    if not settings.hosted:
        return _err("plans exist only with MODE=hosted")
    ensure_data_dir(settings)
    run_migrations(settings.database_url, settings.secret_key)
    with make_session_factory(settings.database_url)() as db:
        if args.action == "list":
            for p in service.plans(db):
                print(json.dumps(service.plan_view(p)))
            return 0
        plan = db.get(Plan, args.code)
        if plan is None:
            return _err(f"no plan {args.code!r}")
        if args.action == "set-price":
            cur = args.currency.upper()
            want = "razorpay" if cur == "INR" else "stripe"
            if args.provider != want:
                return _err(f"{cur} is sold through {want}")
            prices = json.loads(plan.prices or "{}")
            prices[cur] = {
                "amount_minor": args.amount_minor,
                "provider": args.provider,
                "provider_plan_id": args.provider_plan_id,
            }
            plan.prices = json.dumps(prices)
        else:  # set-limit
            if args.key not in service.LIMIT_KEYS:
                return _err(f"unknown limit {args.key!r} ({', '.join(service.LIMIT_KEYS)})")
            limits = json.loads(plan.limits or "{}")
            if args.value <= 0:
                limits.pop(args.key, None)
            else:
                limits[args.key] = args.value
            plan.limits = json.dumps(limits)
        plan.updated_at = utcnow()
        db.commit()
        print(json.dumps(service.plan_view(plan)))
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
    pa = sub.add_parser("platform-admin", help="hosted operator accounts")
    pa_sub = pa.add_subparsers(dest="action", required=True)
    pc = pa_sub.add_parser("create", help="create an operator (asks for a password)")
    pc.add_argument("email")
    pl = sub.add_parser("plans", help="paid plans (hosted)")
    pl_sub = pl.add_subparsers(dest="action", required=True)
    pl_sub.add_parser("list", help="print every plan as JSON")
    sp = pl_sub.add_parser("set-price", help="price for one currency")
    sp.add_argument("code")
    sp.add_argument("currency", help="INR (razorpay) or USD/EUR/GBP (stripe)")
    sp.add_argument("amount_minor", type=int, help="e.g. 49900 = INR 499.00")
    sp.add_argument("provider", choices=["razorpay", "stripe"])
    sp.add_argument("provider_plan_id", help="Razorpay plan_... or Stripe price_...")
    sl = pl_sub.add_parser("set-limit", help="plan limit (0 removes it)")
    sl.add_argument("code")
    sl.add_argument("key")
    sl.add_argument("value", type=int)
    args = parser.parse_args(argv)
    if args.command == "reset-password":
        return reset_password(args.email)
    if args.command == "platform-admin":
        return create_platform_admin(args.email)
    if args.command == "plans":
        return plans_cmd(args)
    if args.command == "invite":
        return create_invite(args.note, args.days)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
