"""Static tenant-isolation check (AST over source files, no DB).

Method: every function in ``mebot`` that builds a query (select/update/delete/exists, or
db.get/db.query) touching a tenant model -- a model with a ``bot_id`` column -- must
scope each such model in the same function, by one of:

- ``Model.bot_id`` appearing in the function (a filter such as ``Model.bot_id == bot_id``);
- a correlated subquery ``Model.<col> == Other.id`` where Other is itself a tenant model
  (the outer query's bot filter scopes it, e.g. messages of a session);
- for ``db.get(Model, id)``: a ``<row>.bot_id`` comparison afterwards (fetch, then check).

``mebot.repos`` functions must additionally take ``bot_id`` as a parameter, so callers
can't forget it. Helpers that only touch a row they were handed build no query and are
not checked. Deliberate cross-tenant helpers (system jobs) are listed in ALLOWED with the
reason; adding one is a reviewed decision. The test fails on new unscoped queries anywhere
in the package, not just in repos.
"""

import ast
import inspect
import pkgutil
from importlib import import_module

import mebot
import mebot.repos
from mebot import models

TENANT_MODELS = {
    name
    for name, obj in vars(models).items()
    if inspect.isclass(obj)
    and issubclass(obj, models.Base)
    and obj is not models.Base
    and "bot_id" in obj.__table__.c
    and obj.__tablename__ != "admin_sessions"  # keyed by admin; see test below
    and obj.__tablename__ != "admins"  # login looks admins up by e-mail, before any bot
    and obj.__tablename__ != "slug_redirects"  # looked up by old slug, before any bot
}

QUERY_CALLS = {"select", "update", "delete", "exists"}

# (module, function): why it may span tenants.
ALLOWED = {
    ("mebot.repos.import_jobs", "purge_expired"): "system job: expired drafts of every bot",
    ("mebot.limits.counters", "purge"): "system job: expired rate-limit windows",
    ("mebot.telegram.outbox", "purge"): "system job: old delivered notifications",
    ("mebot.telegram.outbox", "send_due"): "worker: each row is sent with its own bot's config",
    ("mebot.telegram.repo", "all_configured"): "worker: lists every linked bot",
}


def _functions(pkg=mebot.repos):
    for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        mod = import_module(info.name)
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        for node in fns:
            node.siblings = {f.name: f for f in fns}  # same-module helpers
            yield info.name, node


def _queried_models(fn: ast.FunctionDef) -> set[str]:
    found = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        if name in QUERY_CALLS or name in ("get", "query") and _is_db(f):
            for arg in ast.walk(node):
                if isinstance(arg, ast.Name) and arg.id in TENANT_MODELS:
                    found.add(arg.id)
                if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                    if arg.value.id in TENANT_MODELS:
                        found.add(arg.value.id)
    return found


def _is_db(f) -> bool:
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "db"


def _attr_of(node, model=None) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if model is None or node.value.id == model:
            return node.attr
    return None


def _filters_bot_id(fn: ast.FunctionDef, model: str) -> bool:
    for node in ast.walk(fn):
        if _attr_of(node, model) == "bot_id":
            return True
        if isinstance(node, ast.Compare) and len(node.comparators) == 1:
            left, right = node.left, node.comparators[0]
            for a, b in ((left, right), (right, left)):
                if (
                    _attr_of(a, model)
                    and _attr_of(b) == "id"
                    and b.value.id in TENANT_MODELS
                    and b.value.id != model
                ):
                    return True
    return _get_then_check(fn, model) or _only_correlated(fn, model) or _via_helper(fn, model)


def _only_correlated(fn: ast.FunctionDef, model: str) -> bool:
    """Model only appears as ``Model.id`` on the outer side of a correlated subquery."""
    refs = [n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and _attr_of(n, model)]
    ok = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and len(node.comparators) == 1:
            pair = (node.left, node.comparators[0])
            for a, b in (pair, pair[::-1]):
                if _attr_of(a, model) == "id" and _attr_of(b) and b.value.id in TENANT_MODELS:
                    ok.add(id(a))
    return bool(refs) and all(id(r) in ok for r in refs)


def _via_helper(fn: ast.FunctionDef, model: str) -> bool:
    """Filters come from a same-module helper called with bot_id that scopes the model."""
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        helper = getattr(fn, "siblings", {}).get(node.func.id)
        passes_bot = any(isinstance(a, ast.Name) and a.id == "bot_id" for a in node.args)
        if helper is not None and helper is not fn and passes_bot:
            if any(_attr_of(n, model) == "bot_id" for n in ast.walk(helper)):
                return True
    return False


def _get_then_check(fn: ast.FunctionDef, model: str) -> bool:
    gets = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get"
        and n.args
        and isinstance(n.args[0], ast.Name)
        and n.args[0].id == model
        for n in ast.walk(fn)
    )
    checks = any(
        isinstance(n, ast.Compare)
        and any(_attr_of(x) == "bot_id" for x in [n.left, *n.comparators])
        for n in ast.walk(fn)
    )
    return gets and checks


def test_tenant_models_found():
    assert {"Message", "ChatSession", "LearnedFact", "WidgetSettings"} <= TENANT_MODELS


def test_every_tenant_query_filters_on_bot_id():
    problems = []
    for mod, fn in _functions(mebot):
        if (mod, fn.name) in ALLOWED:
            continue
        queried = _queried_models(fn)
        if not queried:
            continue
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        if mod.startswith("mebot.repos.") and "bot_id" not in params:
            problems.append(f"{mod}.{fn.name}: queries {sorted(queried)} without a bot_id param")
            continue
        for model in sorted(queried):
            if not _filters_bot_id(fn, model):
                problems.append(f"{mod}.{fn.name}: no {model}.bot_id filter")
    assert not problems, "\n".join(problems)


def test_allowlist_entries_exist():
    names = {(mod, fn.name) for mod, fn in _functions(mebot)}
    assert set(ALLOWED) <= names, set(ALLOWED) - names


def test_checker_catches_a_missing_filter():
    src = (
        "def leaky(db, bot_id, sid):\n"
        "    return db.scalar(select(ChatSession).where(ChatSession.id == sid))\n"
    )
    fn = ast.parse(src).body[0]
    assert _queried_models(fn) == {"ChatSession"}
    assert not _filters_bot_id(fn, "ChatSession")


def test_checker_accepts_correlated_and_get_then_check():
    corr = ast.parse(
        "def f(bot_id):\n"
        "    return select(Message.id).where(Message.session_id == ChatSession.id).exists()\n"
    ).body[0]
    assert _filters_bot_id(corr, "Message")
    got = ast.parse(
        "def g(db, cid, bot):\n"
        "    c = db.get(Contact, cid)\n"
        "    if c is None or c.bot_id != bot.id:\n"
        "        return None\n"
    ).body[0]
    assert _queried_models(got) == {"Contact"} and _filters_bot_id(got, "Contact")
