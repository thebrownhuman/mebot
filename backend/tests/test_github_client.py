import logging

import httpx
import pytest
import respx

from mebot.imports import github
from tests.conftest import csrf
from tests.github_fixtures import API, README, b64, mock_repo, repo_meta, requested


async def fetch(token=None, **kw):
    async with github.GitHubClient(token) as gh:
        return await gh.fetch_repo("shivansh", "mebot")


@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_fetch_repo_reads_only_allow_listed_files(respx_mock):
    mock_repo(respx_mock)
    data = await fetch()
    assert data.meta["name"] == "mebot" and data.languages["Python"] == 60_000
    assert data.readme == README
    assert set(data.files) == {"frontend/package.json", "backend/requirements.txt", "Dockerfile"}
    assert {"vercel.json", "main.tf", ".github/workflows/ci.yml", "frontend/vite.config.ts"} <= set(
        data.paths
    )
    reqs = requested(respx_mock)
    assert all(r.url.host == "api.github.com" and r.url.scheme == "https" for r in reqs)
    paths = [r.url.path for r in reqs]
    # names-only and non-allow-listed files are never fetched; no recursion past the limits
    for never in ("vercel.json", "main.tf", "ci.yml", "secrets.env", "main.py", "vite.config.ts",
                  "README.md", "t-docs", "t-src"):  # fmt: skip
        assert not any(p.endswith(never) for p in paths), never
    assert all("recursive" not in str(r.url) for r in reqs)
    content = [r for r in reqs if "/contents/" in r.url.path]
    assert all(r.url.params["ref"] == "main" for r in content)


@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_token_header_only_when_set(respx_mock):
    mock_repo(respx_mock)
    await fetch()
    assert "authorization" not in requested(respx_mock)[0].headers
    respx_mock.calls.reset()
    await fetch(token="ghp_SECRET123")
    assert requested(respx_mock)[-1].headers["authorization"] == "Bearer ghp_SECRET123"


@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_readme_capped_and_missing(respx_mock):
    mock_repo(respx_mock, readme="x" * 40_000)
    assert len((await fetch()).readme) == github.README_CAP
    respx_mock.reset()
    respx_mock.routes.clear()
    mock_repo(respx_mock, readme=None)
    assert (await fetch()).readme is None


@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_manifest_caps(respx_mock, monkeypatch):
    monkeypatch.setattr(github, "MAX_MANIFESTS", 1)
    mock_repo(respx_mock)
    data = await fetch()
    assert list(data.files) == ["Dockerfile"]  # shallowest first
    assert any("more than 1 manifests" in n for n in data.notes)


@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_big_manifest_skipped(respx_mock, monkeypatch):
    monkeypatch.setattr(github, "MANIFEST_MAX_BYTES", 150)
    mock_repo(respx_mock)
    data = await fetch()
    assert "frontend/package.json" not in data.files
    assert any("larger than 200 KB" in n for n in data.notes)


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(404, json={}), "REPO_NOT_FOUND"),
        (
            httpx.Response(
                403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"}
            ),
            "GITHUB_RATE_LIMITED",
        ),  # fmt: skip
        (httpx.Response(429), "GITHUB_RATE_LIMITED"),
        (httpx.Response(500), "GITHUB_UNAVAILABLE"),
        (httpx.Response(403), "GITHUB_UNAVAILABLE"),
    ],
)
async def test_error_mapping(response, code):
    with respx.mock(assert_all_mocked=True) as m:
        m.get(f"{API}/repos/shivansh/mebot").mock(return_value=response)
        with pytest.raises(github.GitHubError) as e:
            await fetch()
    assert e.value.code == code
    if code == "GITHUB_RATE_LIMITED" and response.status_code == 403:
        assert "22:13 UTC" in e.value.message and "token" in e.value.message


async def test_timeout_mapped_and_token_not_leaked(caplog):
    caplog.set_level(logging.DEBUG)
    with respx.mock(assert_all_mocked=True) as m:
        m.get(f"{API}/repos/shivansh/mebot").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(github.GitHubError) as e:
            await fetch(token="ghp_SECRET123")
    assert e.value.code == "GITHUB_UNAVAILABLE"
    assert "ghp_SECRET123" not in e.value.message and "ghp_SECRET123" not in caplog.text


async def test_other_hosts_refused_even_on_redirect():
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as m:
        m.get(f"{API}/repos/shivansh/mebot").mock(
            return_value=httpx.Response(302, headers={"location": "https://evil.dev/steal"})
        )
        evil = m.get("https://evil.dev/steal").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(github.GitHubError):
            await fetch()
    assert not evil.called


async def test_malformed_base64_is_skipped():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as m:
        mock_repo(m)
        m.get(f"{API}/repos/shivansh/mebot/contents/Dockerfile").mock(
            return_value=httpx.Response(200, json={"encoding": "base64", "content": "@@@"})
        )
        data = await fetch()
    assert "Dockerfile" not in data.files


# --- the picker endpoint -----------------------------------------------------------------


def rows():
    def r(name, stars, pushed, **kw):
        return {"name": name, "full_name": f"shivansh/{name}", "stargazers_count": stars,
                "pushed_at": pushed, "fork": False, "archived": False, "language": "Go",
                "description": None, **kw}  # fmt: skip

    return [
        r("old", 1, "2024-01-01T00:00:00Z"),
        r("star", 50, "2025-01-01T00:00:00Z"),
        r("new", 1, "2026-10-01T00:00:00Z"),
        r("fork", 99, "2026-10-01T00:00:00Z", fork=True),
        r("archived", 99, "2026-10-01T00:00:00Z", archived=True),
    ]


def test_repo_picker_sorted_and_forks_hidden(admin_client):
    with respx.mock(assert_all_mocked=True) as m:
        route = m.get(f"{API}/users/shivansh/repos").mock(
            return_value=httpx.Response(200, json=rows())
        )
        r = admin_client.get("/api/admin/import/github/repos?username=shivansh")
        assert r.status_code == 200, r.text
        assert [i["name"] for i in r.json()["items"]] == ["star", "new", "old", "archived"]
        assert route.calls[0].request.url.params["type"] == "owner"
        r = admin_client.get("/api/admin/import/github/repos?username=shivansh&include_forks=true")
        assert "fork" in [i["name"] for i in r.json()["items"]]
    item = r.json()["items"][0]
    assert set(item) >= {
        "name",
        "full_name",
        "description",
        "language",
        "stars",
        "pushed_at",
        "fork",
        "archived",
    }


def test_repo_picker_errors(admin_client):
    assert admin_client.get("/api/admin/import/github/repos?username=bad/name").status_code == 422
    with respx.mock(assert_all_mocked=True) as m:
        m.get(f"{API}/users/ghost/repos").mock(return_value=httpx.Response(404, json={}))
        r = admin_client.get("/api/admin/import/github/repos?username=ghost")
        assert r.status_code == 404 and r.json()["error"]["code"] == "USER_NOT_FOUND"
        m.get(f"{API}/users/busy/repos").mock(
            return_value=httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
        )
        r = admin_client.get("/api/admin/import/github/repos?username=busy")
        assert r.status_code == 429 and r.json()["error"]["code"] == "GITHUB_RATE_LIMITED"


def test_repo_picker_requires_admin(client):
    from tests.conftest import do_setup

    do_setup(client)
    client.cookies.delete("mebot_session")
    assert client.get("/api/admin/import/github/repos?username=x").status_code == 401
    assert csrf  # noqa: B018 - shared helper import


def test_meta_fixture_sane():
    assert repo_meta()["default_branch"] == "main" and b64("x")["encoding"] == "base64"
