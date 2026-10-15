from datetime import date

from mebot import evals
from mebot.marker import UNANSWERED_MARKER


class ScriptedClient:
    """Answers each golden question with a canned reply (no network)."""

    def __init__(self, answers: dict[str, str]):
        self.answers = answers
        self.prompts: list[str] = []

    async def stream_chat(self, messages, *, model, temperature, max_tokens):
        self.prompts.append(messages[0]["content"])
        reply = self.answers.get(messages[-1]["content"], "I don't know.")
        for i in range(0, len(reply), 5):
            yield reply[i : i + 5]


def test_golden_file_and_sample_profile_load():
    golden = evals.load_golden()
    assert len(golden.cases) >= 20
    assert golden.as_of == date(2026, 10, 16)
    ids = {c.id for c in golden.cases}
    assert {"total_years", "python_years", "injection", "off_topic", "avoid_topic"} <= ids
    assert golden.profile.identity["full_name"]
    assert golden.profile.items("experiences")


def test_check_rules():
    case = evals.Case(
        id="x",
        question="q",
        expect_any=["4 years 4 months", "4.3"],
        expect_all=["acme"],
        expect_not=["10 years"],
        expect_unanswered=False,
    )
    assert evals.check(case, "I have 4.3 years, now at Acme.").ok
    r = evals.check(case, "I have 10 years at Acme, 4.3 total.")
    assert not r.ok and "10 years" in r.reason
    assert not evals.check(case, "4.3 years elsewhere").ok
    assert not evals.check(case, f"4.3 at Acme {UNANSWERED_MARKER}").ok
    unans = evals.Case(id="u", question="q", expect_unanswered=True)
    assert evals.check(unans, f"Not sure. {UNANSWERED_MARKER}").ok
    assert evals.check(unans, "Not sure. [[ unanswered ]]").ok
    assert not evals.check(unans, "Here is a made-up answer.").ok


async def test_run_against_scripted_client():
    golden = evals.load_golden()
    total = golden.cases[0]
    client = ScriptedClient({total.question: "About 4 years 4 months (4.3 years) in total."})
    results = await evals.run(golden, client, model="m", cases=[total])
    assert [r.ok for r in results] == [True]
    prompt = client.prompts[0]
    assert "=== FACTS (computed by the system as of 2026-10-16" in prompt
    assert "Total professional experience: 4 years 4 months (4.3 years)" in prompt


def test_cli_requires_configured_bot(tmp_path, monkeypatch, capsys):
    from mebot.config import Settings

    s = Settings(
        _env_file=None,
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'e.db').as_posix()}",
    )
    monkeypatch.setattr(evals, "Settings", lambda: s)
    assert evals.main(["--bot", "default"]) == 2
    assert "no working ai provider" in capsys.readouterr().err.lower()
