"""Aggregates for GET /v1/stats, the weekly summary and /stats. No personal data."""

from collections import Counter
from datetime import datetime, timedelta

from app.db import Database, iso


def compute(db: Database, now: datetime) -> dict:
    d7, d30 = iso(now - timedelta(days=7)), iso(now - timedelta(days=30))
    with db.tx() as c:
        active_7d = c.execute(
            "SELECT COUNT(*) FROM installs WHERE last_seen >= ?", (d7,)
        ).fetchone()[0]
        active_30d = c.execute(
            "SELECT COUNT(*) FROM installs WHERE last_seen >= ?", (d30,)
        ).fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM installs").fetchone()[0]
        new_installs = c.execute(
            "SELECT COUNT(*) FROM installs WHERE first_seen >= ?", (d7,)
        ).fetchone()[0]
        versions = Counter()
        modes = Counter()
        for row in c.execute("SELECT version, mode FROM installs WHERE last_seen >= ?", (d7,)):
            versions[row["version"]] += 1
            modes[row["mode"]] += 1
        registrations = c.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        new_registrations = c.execute(
            "SELECT COUNT(*) FROM registrations WHERE created_at >= ?", (d7,)
        ).fetchone()[0]
    return {
        "active_7d": active_7d,
        "active_30d": active_30d,
        "total_installs": total,
        "new_installs_7d": new_installs,
        "by_version": dict(sorted(versions.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_mode": dict(sorted(modes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "registrations": registrations,
        "new_registrations_7d": new_registrations,
    }
