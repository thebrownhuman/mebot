"""Evals for retrieval mode. No network: these measure what the model would be *shown*.

The real-provider golden run (``python -m mebot.evals --retrieval always``) needs an API key
and is not part of CI; here the proxy is evidence recall: every expected answer fragment
that the full profile contains must still reach the model in ``always`` mode (in the
retrieved excerpts, the always-on blocks or the outline).
"""

from mebot import evals
from mebot.profile.render import render_profile
from mebot.retrieval.service import retrieval_knowledge
from tests.retrieval_fixtures import large_profile


class Scripted:
    def __init__(self):
        self.prompts: list[str] = []

    async def stream_chat(self, messages, *, model, temperature, max_tokens):
        self.prompts.append(messages[0]["content"])
        yield "ok"


def test_golden_questions_keep_their_evidence_in_always_mode():
    golden = evals.load_golden()
    full = render_profile(golden.profile, as_of=golden.as_of).lower()
    lost = []
    checked = 0
    for case in golden.cases:
        shown = retrieval_knowledge(
            golden.profile, [case.question], budget=2500, as_of=golden.as_of
        ).text.lower()
        for token in case.expect_all:
            if token.lower() in full:
                checked += 1
                if token.lower() not in shown:
                    lost.append((case.id, token))
        wanted = [t for t in case.expect_any if t.lower() in full]
        if wanted:
            checked += 1
            if not any(t.lower() in shown for t in wanted):
                lost.append((case.id, wanted))
    assert checked > 15
    assert lost == []


def test_golden_questions_get_the_same_always_on_blocks():
    golden = evals.load_golden()
    for case in golden.cases:
        text = retrieval_knowledge(
            golden.profile, [case.question], budget=2500, as_of=golden.as_of
        ).text
        for block in ("=== FACTS", "=== IDENTITY", "=== CONTACT CHANNELS", "=== PROFILE OUTLINE"):
            assert block in text, (case.id, block)
        assert "912" not in text and "alex_private" not in text  # non-shared channels stay out


async def test_run_in_retrieval_mode_builds_excerpted_prompts():
    golden = evals.load_golden()
    client = Scripted()
    results = await evals.run(golden, client, model="m", cases=golden.cases[:3], retrieval=True)
    assert len(results) == 3
    assert all(
        "=== PROFILE OUTLINE" in p and "PROFILE excerpts and OUTLINE" in p for p in client.prompts
    )
    full = Scripted()
    await evals.run(golden, full, model="m", cases=golden.cases[:3])
    assert all("PROFILE OUTLINE" not in p for p in full.prompts)


def test_large_profile_deep_items_are_retrieved():
    p = large_profile()
    misses = []
    for i in range(40):
        what = [
            "streaming ingestion pipeline",
            "memory-safe packet parser",
            "multi-region infrastructure modules",
            "federated gateway",
            "product search relevance tuning",
            "offline-first mobile client",
            "distributed rate limiter",
            "autoscaling job scheduler",
            "partitioned analytics warehouse",
            "in-browser image editor",
        ][i % 10]
        topic = ["Kafka", "Rust", "Terraform", "GraphQL", "Elasticsearch", "Flutter", "Redis",
                 "Kubernetes", "PostgreSQL", "WebAssembly"][i % 10]  # fmt: skip
        k = retrieval_knowledge(p, [f"Tell me about the {what} number {i}"], budget=2500)
        if f"Project {topic} {i}" not in k.titles:
            misses.append(i)
        assert not k.fallback
    assert misses == []


def test_large_profile_jobs_are_retrieved_and_most_of_it_is_left_out():
    p = large_profile()
    for i in range(10):
        k = retrieval_knowledge(
            p, [f"what did he do on the unique-widget-{i} platform?"], budget=2500
        )
        assert f"Engineer level {i} at Company{i}" in k.titles, i
    k = retrieval_knowledge(p, ["Tell me about the federated gateway"], budget=2500)
    full_tokens = len(render_profile(p)) // 4
    assert k.prompt_tokens < full_tokens / 3  # the saving retrieval is for


def test_vague_question_gets_fallback_not_nothing():
    k = retrieval_knowledge(large_profile(), ["Why should we hire him?"], budget=2500)
    assert k.titles  # latest job + top projects, never an empty excerpt block
    assert "=== PROFILE EXCERPTS" in k.text
