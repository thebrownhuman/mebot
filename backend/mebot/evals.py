"""Golden-question evals against a real provider (not run in CI).

    python -m mebot.evals --bot default [--golden evals/golden.yaml] [--case total_years]

Uses the bot's configured provider/model/key but the sample profile shipped with the
golden file (the expectations are written for it), with dates frozen at the golden
``as_of``. Prints pass/fail per question; exit code 1 if any fail.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from mebot import channels, persona
from mebot.config import BACKEND_DIR, Settings, ensure_data_dir, resolve_secret_key
from mebot.db import make_session_factory, run_migrations
from mebot.guard.channels import ChannelGuard
from mebot.llm import service as llm
from mebot.marker import MARKER_RE, PERSONAL_RE
from mebot.profile.data import ProfileData
from mebot.profile.render import render_profile
from mebot.profile.schemas import IdentityIn
from mebot.profile.sections import SECTIONS
from mebot.prompt import build_system_prompt
from mebot.repos import bots

DEFAULT_GOLDEN = BACKEND_DIR / "evals" / "golden.yaml"


@dataclass
class Case:
    id: str
    question: str
    expect_any: list[str] = field(default_factory=list)  # at least one must appear
    expect_all: list[str] = field(default_factory=list)  # every one must appear
    expect_not: list[str] = field(default_factory=list)  # none may appear
    expect_unanswered: bool = False
    expect_personal: bool = False  # must decline and end with [[PERSONAL]]


@dataclass
class Golden:
    as_of: date
    profile: ProfileData
    cases: list[Case]


@dataclass
class Result:
    case: Case
    ok: bool
    reason: str = ""
    answer: str = ""


def load_profile_fixture(path: Path) -> ProfileData:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sections = {}
    for slug, sec in SECTIONS.items():
        # Validate through the same schemas as the API so the fixture can't drift.
        sections[slug] = [sec.schema.model_validate(i).model_dump() for i in raw.get(slug, [])]
    return ProfileData(
        identity=IdentityIn.model_validate(raw.get("identity", {})).model_dump(),
        notes=raw.get("notes", ""),
        sections=sections,
    )


def load_golden(path: Path = DEFAULT_GOLDEN) -> Golden:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    as_of = raw["as_of"]
    return Golden(
        as_of=as_of if isinstance(as_of, date) else date.fromisoformat(as_of),
        profile=load_profile_fixture(path.parent / raw["profile"]),
        cases=[Case(**c) for c in raw["cases"]],
    )


def check(case: Case, answer: str) -> Result:
    unanswered = bool(MARKER_RE.search(answer))
    personal = bool(PERSONAL_RE.search(answer))
    if case.expect_personal != personal:
        return Result(
            case,
            False,
            "expected the PERSONAL marker" if personal is False else "unexpected PERSONAL marker",
            answer,
        )
    low = answer.lower()
    if case.expect_unanswered and not unanswered:
        return Result(case, False, "expected the UNANSWERED marker", answer)
    if not case.expect_unanswered and unanswered:
        return Result(case, False, "unexpected UNANSWERED marker", answer)
    for bad in case.expect_not:
        if bad.lower() in low:
            return Result(case, False, f"must not contain {bad!r}", answer)
    missing = [s for s in case.expect_all if s.lower() not in low]
    if missing:
        return Result(case, False, f"missing {missing}", answer)
    if case.expect_any and not any(s.lower() in low for s in case.expect_any):
        return Result(case, False, f"needs one of {case.expect_any}", answer)
    return Result(case, True, "", answer)


async def run(
    golden: Golden,
    client,
    *,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 400,
    cases: list[Case] | None = None,
) -> list[Result]:
    system = build_system_prompt(
        render_profile(golden.profile, as_of=golden.as_of),
        golden.as_of,
        name=persona.display_name(golden.profile.identity),
        pronouns=golden.profile.identity.get("pronouns") or persona.DEFAULT_PRONOUNS,
    )
    results = []
    for case in cases or golden.cases:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": case.question},
        ]
        try:
            chunks = [
                c
                async for c in client.stream_chat(
                    messages, model=model, temperature=temperature, max_tokens=max_tokens
                )
            ]
            # Same output guard as the chat route: non-shared contact values become [hidden].
            guard = ChannelGuard(channels.from_items(golden.profile.items("links")))
            answer = guard.feed("".join(chunks)) + guard.finish()
            results.append(check(case, answer))
        except Exception as e:  # noqa: BLE001 - report and keep going
            results.append(Result(case, False, f"provider error: {e}", ""))
    return results


def _client_for(slug: str):
    settings = Settings()
    ensure_data_dir(settings)
    run_migrations(settings.database_url)
    secret = resolve_secret_key(settings)
    with make_session_factory(settings.database_url)() as db:
        bot = bots.get_by_slug(db, slug)
        if bot is None and slug == "default":
            bot = bots.get_primary(db)  # setup renames the default bot
        if bot is None:
            return None, None
        _, _, cfg = llm.load(db, bot.id, secret)
    return (cfg.client(), cfg) if cfg else (None, None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mebot.evals")
    ap.add_argument("--bot", default="default", help="bot slug whose provider to use")
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    ap.add_argument("--case", action="append", help="only run these case ids")
    args = ap.parse_args(argv)

    client, cfg = _client_for(args.bot)
    if client is None:
        print(f"mebot evals: no working AI provider for bot {args.bot!r}", file=sys.stderr)
        return 2
    golden = load_golden(args.golden)
    cases = [c for c in golden.cases if not args.case or c.id in args.case]
    results = asyncio.run(
        run(golden, client, model=cfg.model, temperature=cfg.temperature, cases=cases)
    )
    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'}  {r.case.id:<22} {r.reason}")
        if not r.ok and r.answer:
            print(f"      answer: {r.answer.strip()[:300]}")
    passed = sum(r.ok for r in results)
    print(f"\n{passed}/{len(results)} passed ({cfg.provider} / {cfg.model})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
