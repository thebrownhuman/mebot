"""GitHub import: repo URLs -> project entries.

Only https://api.github.com is ever requested: a request hook refuses every other host
(including redirects), and links found in READMEs or manifests are never followed.
Only an allow-list of manifests is fetched; other files are seen by name at most.
"""

import base64
import binascii
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from mebot.imports.filetype import ImportFailure

MAX_REPOS = 10
_PART = r"[A-Za-z0-9_.-]{1,100}"
_URL = re.compile(
    rf"^https?://(?:www\.)?github\.com/({_PART})/({_PART})"
    r"(?:/(?:tree|blob)/[^\s?#]*)?/?(?:[?#]\S*)?$",
    re.IGNORECASE,
)
_BAD_URL = "Use a GitHub repo URL like https://github.com/owner/repo."


def parse_repo_url(raw: str) -> tuple[str, str]:
    """(owner, repo) from https://github.com/{owner}/{repo}[.git][/][/tree/...]."""
    m = _URL.match((raw or "").strip())
    if not m:
        raise ImportFailure("INVALID_REPO_URL", _BAD_URL)
    owner, repo = m.group(1), m.group(2)
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not repo or owner in (".", "..") or repo in (".", ".."):
        raise ImportFailure("INVALID_REPO_URL", _BAD_URL)
    return owner, repo


def repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


# --- client ------------------------------------------------------------------------------

API_HOST = "api.github.com"
API = f"https://{API_HOST}"
CALL_TIMEOUT = 10.0
README_CAP = 30_000
MANIFEST_MAX_BYTES = 200 * 1024
MAX_MANIFESTS = 15
MAX_TREE_CALLS = 12
COMMON_DIRS = {"frontend", "backend", "client", "server", "web", "api", "apps", "packages"}
NESTED_DIRS = {"apps", "packages"}  # one more level: apps/web, packages/ui, ...

# Dependency manifests: their content is fetched and parsed.
CONTENT_PATTERNS = (
    r"package\.json",
    r"requirements[\w.-]*\.txt",
    r"pyproject\.toml",
    r"Pipfile",
    r"go\.mod",
    r"Cargo\.toml",
    r"pom\.xml",
    r"build\.gradle(\.kts)?",
    r"composer\.json",
    r"Gemfile",
    r"pubspec\.yaml",
    r"Dockerfile",
    r"docker-compose[\w.-]*\.ya?ml",
    r"schema\.prisma",
)
# Detected by name alone: never fetched.
NAME_PATTERNS = (
    r"vercel\.json",
    r"netlify\.toml",
    r"fly\.toml",
    r"railway\.toml",
    r"[\w.-]+\.tf",
    r"angular\.json",
    r"next\.config\.\w+",
    r"vite\.config\.\w+",
    r"tailwind\.config\.\w+",
)
_CONTENT = re.compile("^(?:" + "|".join(CONTENT_PATTERNS) + ")$")
_NAME = re.compile("^(?:" + "|".join(NAME_PATTERNS) + ")$")
_WORKFLOW = re.compile(r"^\.github/workflows/[\w.-]+\.ya?ml$")


def is_content_manifest(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if base == "schema.prisma":
        return path in ("schema.prisma", "prisma/schema.prisma") or path.endswith(
            "/prisma/schema.prisma"
        )
    return bool(_CONTENT.match(base))


def is_name_manifest(path: str) -> bool:
    return bool(_NAME.match(path.rsplit("/", 1)[-1])) or bool(_WORKFLOW.match(path))


class GitHubError(ImportFailure):
    pass


@dataclass
class RepoData:
    owner: str
    repo: str
    meta: dict
    languages: dict[str, int] = field(default_factory=dict)
    readme: str | None = None
    # path -> text for fetched dependency manifests
    files: dict[str, str] = field(default_factory=dict)
    # every path seen in the trees (names only)
    paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _reset_hint(headers) -> str:
    reset = headers.get("x-ratelimit-reset")
    when = ""
    if reset and reset.isdigit():
        when = " after " + datetime.fromtimestamp(int(reset), UTC).strftime("%H:%M UTC")
    return (
        f"GitHub's rate limit was reached; try again{when}. Adding a GitHub token "
        "(no scopes needed) raises the limit."
    )


async def _only_github(request: httpx.Request) -> None:
    # Every request, including redirects, must stay on the API host.
    if request.url.scheme != "https" or request.url.host != API_HOST:
        raise httpx.InvalidURL("only api.github.com may be requested")


class GitHubClient:
    def __init__(self, token: str | None = None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "mebot-import"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(
            base_url=API,
            headers=headers,
            timeout=CALL_TIMEOUT,
            follow_redirects=True,
            event_hooks={"request": [_only_github]},
        )
        self.tree_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()

    async def get(
        self, path: str, params: dict | None = None, *, not_found: str = "REPO_NOT_FOUND"
    ):
        if not path.startswith("/") or "://" in path or ".." in path.split("/"):
            raise GitHubError("GITHUB_UNAVAILABLE", "Refused an unexpected GitHub path.")
        try:
            r = await self._http.get(path, params=params)
        except httpx.TimeoutException:
            raise GitHubError("GITHUB_UNAVAILABLE", "GitHub didn't answer in time.", 502) from None
        except (httpx.HTTPError, httpx.InvalidURL):  # InvalidURL: our host guard fired
            raise GitHubError("GITHUB_UNAVAILABLE", "Couldn't reach GitHub.", 502) from None
        if r.status_code == 429 or (
            r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise GitHubError("GITHUB_RATE_LIMITED", _reset_hint(r.headers), 429)
        if r.status_code == 404:
            message = (
                "GitHub user not found."
                if not_found == "USER_NOT_FOUND"
                else "Repo not found (private repos can't be imported)."
            )
            raise GitHubError(not_found, message, 404)
        if r.status_code >= 400:
            raise GitHubError("GITHUB_UNAVAILABLE", f"GitHub answered {r.status_code}.", 502)
        try:
            return r.json()
        except ValueError:
            raise GitHubError(
                "GITHUB_UNAVAILABLE", "GitHub sent an unreadable answer.", 502
            ) from None

    async def user_repos(self, username: str) -> list[dict]:
        data = await self.get(
            f"/users/{quote(username, safe='')}/repos",
            {"type": "owner", "per_page": 100, "sort": "pushed"},
            not_found="USER_NOT_FOUND",
        )
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    async def _tree(self, o: str, r: str, ref: str) -> list[dict]:
        if self.tree_calls >= MAX_TREE_CALLS:
            return []
        self.tree_calls += 1
        data = await self.get(f"/repos/{o}/{r}/git/trees/{quote(ref, safe='')}")
        tree = data.get("tree") if isinstance(data, dict) else None
        return [e for e in tree or [] if isinstance(e, dict) and isinstance(e.get("path"), str)]

    async def _decoded(self, path: str, params: dict | None = None) -> str | None:
        data = await self.get(path, params)
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        try:
            raw = re.sub(r"\s", "", str(data.get("content") or ""))
            return base64.b64decode(raw, validate=True).decode("utf-8", errors="replace")
        except (ValueError, binascii.Error):
            return None

    async def fetch_repo(self, o: str, r: str) -> RepoData:
        self.tree_calls = 0
        meta = await self.get(f"/repos/{quote(o)}/{quote(r)}")
        if not isinstance(meta, dict):
            raise GitHubError("GITHUB_UNAVAILABLE", "GitHub sent an unreadable answer.", 502)
        data = RepoData(owner=o, repo=r, meta=meta)
        base = f"/repos/{quote(o)}/{quote(r)}"
        langs = await self.get(f"{base}/languages")
        data.languages = {
            k: v
            for k, v in (langs if isinstance(langs, dict) else {}).items()
            if isinstance(v, int)
        }
        try:
            readme = await self._decoded(f"{base}/readme")
            data.readme = readme[:README_CAP] if readme else None
        except GitHubError as e:
            if e.code != "REPO_NOT_FOUND":
                raise
        branch = str(meta.get("default_branch") or "HEAD")
        blobs = await self._walk(quote(o), quote(r), branch, data)
        manifests = sorted(
            (b for b in blobs if is_content_manifest(b["path"])),
            key=lambda b: (b["path"].count("/"), b["path"]),
        )
        for b in manifests:
            if len(data.files) >= MAX_MANIFESTS:
                data.notes.append(f"{b['path']}: skipped (more than {MAX_MANIFESTS} manifests)")
                continue
            if int(b.get("size") or 0) > MANIFEST_MAX_BYTES:
                data.notes.append(f"{b['path']}: skipped (larger than 200 KB)")
                continue
            text = await self._decoded(f"{base}/contents/{quote(b['path'])}", {"ref": branch})
            if text is not None:
                data.files[b["path"]] = text
        return data

    async def _walk(self, o: str, r: str, branch: str, data: RepoData) -> list[dict]:
        """Root tree + one level into common dirs (two for apps/ and packages/), plus the
        names in .github/workflows and prisma/. Never recursive."""
        blobs: list[dict] = []

        async def visit(sha: str, prefix: str, depth: int):
            for e in await self._tree(o, r, sha):
                path = prefix + e["path"]
                data.paths.append(path)
                if e.get("type") == "blob":
                    blobs.append({**e, "path": path})
                elif e.get("type") == "tree" and isinstance(e.get("sha"), str):
                    name = e["path"]
                    top = prefix.split("/", 1)[0]
                    if depth == 0 and (name in COMMON_DIRS or name in (".github", "prisma")):
                        await visit(e["sha"], path + "/", 1)
                    elif depth == 1 and (
                        top in NESTED_DIRS or (top == ".github" and name == "workflows")
                    ):
                        await visit(e["sha"], path + "/", 2)

        await visit(branch, "", 0)
        return blobs
