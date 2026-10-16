"""GitHub import: repo URLs -> project entries.

Only https://api.github.com is ever requested (see GitHubClient). Links found in
READMEs or manifests are never followed.
"""

import re

from mebot.imports.filetype import ImportFailure

MAX_REPOS = 10
_PART = r"[A-Za-z0-9_.-]{1,100}"
_URL = re.compile(
    rf"^https?://(?:www\.)?github\.com/({_PART})/({_PART})(?:/(?:tree|blob)/[^\s?#]*)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)


def parse_repo_url(raw: str) -> tuple[str, str]:
    """(owner, repo) from https://github.com/{owner}/{repo}[.git][/][/tree/...]."""
    m = _URL.match((raw or "").strip())
    if not m:
        raise ImportFailure(
            "INVALID_REPO_URL", "Use a GitHub repo URL like https://github.com/owner/repo."
        )
    owner, repo = m.group(1), m.group(2)
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not repo or owner in (".", "..") or repo in (".", ".."):
        raise ImportFailure(
            "INVALID_REPO_URL", "Use a GitHub repo URL like https://github.com/owner/repo."
        )
    return owner, repo


def repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"
