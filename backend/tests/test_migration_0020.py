import json

import sqlalchemy as sa

from mebot.db import run_migrations


def test_0020_billing_tables_and_seed(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url, secret_key="k")
    eng = sa.create_engine(url)
    insp = sa.inspect(eng)
    tables = set(insp.get_table_names())
    assert {"plans", "subscriptions", "billing_events", "invoices", "trial_claims"} <= tables
    assert {"terms_version", "terms_accepted_at"} <= {
        c["name"] for c in insp.get_columns("admins")
    }
    for t in ("subscriptions", "invoices", "billing_events"):
        assert insp.get_foreign_keys(t) == []
    with eng.connect() as c:
        rows = {r.code: r for r in c.execute(sa.text("SELECT * FROM plans"))}
    assert set(rows) == {"trial", "monthly"}
    assert rows["trial"].is_trial and not rows["monthly"].is_trial
    assert json.loads(rows["monthly"].prices) == {}
    run_migrations(url, secret_key="k")  # rerun is a no-op
