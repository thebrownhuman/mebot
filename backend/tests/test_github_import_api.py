import json

import pytest

from mebot.imports import github
from mebot.imports.filetype import ImportFailure
from mebot.imports.pipelines import Extracted, Item
from tests.conftest import csrf
from tests.import_fixtures import make_pdf


@pytest.mark.parametrize(
    "raw,want",
    [
        ("https://github.com/shivansh/mebot", ("shivansh", "mebot")),
        ("https://github.com/shivansh/mebot/", ("shivansh", "mebot")),
        ("https://github.com/shivansh/mebot.git", ("shivansh", "mebot")),
        ("https://github.com/shivansh/mebot/tree/main/backend", ("shivansh", "mebot")),
        ("https://github.com/shivansh/mebot/blob/main/README.md", ("shivansh", "mebot")),
        ("https://www.github.com/a-b/c_d.e", ("a-b", "c_d.e")),
        ("  http://GitHub.com/Owner/Repo  ", ("Owner", "Repo")),
        ("https://github.com/o/r?tab=readme", ("o", "r")),
    ],
)
def test_parse_valid(raw, want):
    assert github.parse_repo_url(raw) == want


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "github.com/o/r",
        "https://gitlab.com/o/r",
        "https://github.com/o",
        "https://github.com/o/r/issues/1",
        "https://github.com.evil.dev/o/r",
        "https://evil.dev/github.com/o/r",
        "https://github.com/o/r with space",
        "https://github.com/../r",
        "https://github.com/o/" + "x" * 101,
        "javascript:alert(1)",
    ],
)
def test_parse_invalid(raw):
    with pytest.raises(ImportFailure) as e:
        github.parse_repo_url(raw)
    assert e.value.code == "INVALID_REPO_URL"


@pytest.fixture
def captured(app):
    seen = {}

    async def run(data, ctx):
        seen["repos"] = json.loads(data)["repos"]
        seen["ctx"] = ctx
        return Extracted(sections={"projects": [Item(data={"name": "mebot", "summary": "Bot"})]})

    app.state.import_runners = {**app.state.import_runners, "github": run}
    return seen


def post(c, urls):
    return c.post("/api/admin/import/github", json={"repo_urls": urls}, headers=csrf(c))


def test_creates_github_job_and_dedupes(admin_client, captured):
    r = post(
        admin_client,
        ["https://github.com/a/one", "https://github.com/A/One.git", "https://github.com/a/two/"],
    )
    assert r.status_code == 202, r.text
    assert captured["repos"] == [["a", "one"], ["a", "two"]]
    job = admin_client.get(f"/api/admin/import/jobs/{r.json()['id']}").json()
    assert job["kind"] == "github" and job["status"] == "ready"
    assert job["filename"] == "a/one, a/two"
    assert job["draft"]["sections"]["projects"][0]["data"]["name"] == "mebot"
    assert captured["ctx"].options == {"token": None}


def test_invalid_urls_422_with_fields(admin_client, captured):
    r = post(admin_client, ["https://github.com/a/one", "https://gitlab.com/x/y"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REPO_URL"
    assert r.json()["error"]["details"][0]["field"] == "repo_urls.1"
    assert post(admin_client, []).status_code == 422


def test_too_many_repos(admin_client, captured):
    r = post(admin_client, [f"https://github.com/a/r{i}" for i in range(11)])
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_MANY_REPOS"


def test_auth_csrf_and_not_via_file_upload(client, admin_client, captured):
    r = admin_client.post(
        "/api/admin/import/github", json={"repo_urls": ["https://github.com/a/b"]}
    )
    assert r.status_code == 403
    r = admin_client.post(
        "/api/admin/import/github",
        files={"file": ("x.pdf", make_pdf(["x"]))},
        headers=csrf(admin_client),
    )
    assert r.status_code == 422  # JSON only


def test_llm_optional_and_passed_when_configured(admin_client, captured):
    post(admin_client, ["https://github.com/a/b"])
    assert captured["ctx"].llm is not None and captured["ctx"].llm.model == "gpt-4o-mini"


def test_env_token_passed_in_memory_only(admin_client, app, captured):
    app.state.settings.github_token = "ghp_ENVTOKEN1234"
    r = post(admin_client, ["https://github.com/a/b"])
    assert captured["ctx"].options["token"] == "ghp_ENVTOKEN1234"
    job = admin_client.get(f"/api/admin/import/jobs/{r.json()['id']}").text
    assert "ENVTOKEN" not in job


def test_one_at_a_time_and_rate_limit(admin_client, app, captured):
    from mebot.repos import bots, import_jobs

    for i in range(10):
        assert post(admin_client, [f"https://github.com/a/r{i}"]).status_code == 202
    assert post(admin_client, ["https://github.com/a/x"]).status_code == 429
    with app.state.session_factory() as db:
        import_jobs.create(db, bots.get_primary(db).id, "github", filename="x", sha256="0", size=1)
        db.commit()
    r = post(admin_client, ["https://github.com/a/x"])
    assert r.status_code == 409


def test_per_repo_errors_in_draft(admin_client, app):
    async def run(data, ctx):
        return Extracted(
            sections={"projects": [Item(data={"name": "ok", "summary": "Fine"})]},
            errors=[{"source": "a/missing", "code": "REPO_NOT_FOUND", "message": "Not found"}],
        )

    app.state.import_runners = {**app.state.import_runners, "github": run}
    r = post(admin_client, ["https://github.com/a/ok", "https://github.com/a/missing"])
    job = admin_client.get(f"/api/admin/import/jobs/{r.json()['id']}").json()
    assert job["status"] == "ready"
    assert job["draft"]["errors"] == [
        {"source": "a/missing", "code": "REPO_NOT_FOUND", "message": "Not found"}
    ]
