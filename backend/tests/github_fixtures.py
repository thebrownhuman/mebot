"""A fake api.github.com for respx: one repo with a small tree and manifests."""

import base64
import json

import httpx

API = "https://api.github.com"

PACKAGE_JSON = json.dumps(
    {
        "dependencies": {"react": "^18", "@tanstack/react-query": "^5", "three": "^0.160"},
        "devDependencies": {"vite": "^5", "tailwindcss": "^3", "@types/react": "^18"},
    }
)
REQUIREMENTS = (
    "fastapi>=0.110\nSQLAlchemy==2.0\n# comment\nuvicorn[standard]\nopenai; python_version>'3.8'\n"
)
README = (
    "# mebot\n\nA portfolio chatbot that answers recruiters' questions about the owner.\n"
    "Built with FastAPI and React. Serves 2,000 chats a month.\n"
)


def b64(text: str) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


def repo_meta(**over):
    meta = {
        "name": "mebot",
        "full_name": "shivansh/mebot",
        "owner": {"login": "shivansh"},
        "description": "Portfolio chatbot",
        "homepage": "https://mebot.dev",
        "default_branch": "main",
        "created_at": "2026-07-03T10:00:00Z",
        "pushed_at": "2026-10-16T10:00:00Z",
        "archived": False,
        "fork": False,
        "stargazers_count": 12,
        "language": "Python",
        "topics": ["chatbot"],
    }
    meta.update(over)
    return meta


ROOT_TREE = [
    {"path": "README.md", "type": "blob", "sha": "r1", "size": 300},
    {"path": "frontend", "type": "tree", "sha": "t-front"},
    {"path": "backend", "type": "tree", "sha": "t-back"},
    {"path": "docs", "type": "tree", "sha": "t-docs"},  # not a common dir: never listed
    {"path": ".github", "type": "tree", "sha": "t-gh"},
    {"path": "Dockerfile", "type": "blob", "sha": "d1", "size": 200},
    {"path": "vercel.json", "type": "blob", "sha": "v1", "size": 50},
    {"path": "main.tf", "type": "blob", "sha": "tf1", "size": 50},
    {"path": "secrets.env", "type": "blob", "sha": "s1", "size": 50},
]
FRONT_TREE = [
    {"path": "package.json", "type": "blob", "sha": "p1", "size": 400},
    {"path": "vite.config.ts", "type": "blob", "sha": "vc1", "size": 100},
    {"path": "src", "type": "tree", "sha": "t-src"},  # depth limit: never listed
]
BACK_TREE = [
    {"path": "requirements.txt", "type": "blob", "sha": "q1", "size": 100},
    {"path": "main.py", "type": "blob", "sha": "m1", "size": 100},
]
GH_TREE = [{"path": "workflows", "type": "tree", "sha": "t-wf"}]
WF_TREE = [{"path": "ci.yml", "type": "blob", "sha": "w1", "size": 100}]


def mock_repo(router, owner="shivansh", repo="mebot", meta=None, readme=README, files=None):
    """Register routes for one repo on a respx router; returns the router."""
    base = f"{API}/repos/{owner}/{repo}"
    router.get(base).mock(return_value=httpx.Response(200, json=meta or repo_meta()))
    router.get(f"{base}/languages").mock(
        return_value=httpx.Response(
            200, json={"Python": 60_000, "TypeScript": 38_000, "Shell": 2_000}
        )
    )
    if readme is None:
        router.get(f"{base}/readme").mock(return_value=httpx.Response(404, json={}))
    else:
        router.get(f"{base}/readme").mock(return_value=httpx.Response(200, json=b64(readme)))
    trees = {
        "main": ROOT_TREE,
        "t-front": FRONT_TREE,
        "t-back": BACK_TREE,
        "t-gh": GH_TREE,
        "t-wf": WF_TREE,
    }
    for sha, tree in trees.items():
        router.get(f"{base}/git/trees/{sha}").mock(
            return_value=httpx.Response(200, json={"tree": tree})
        )
    contents = {
        "frontend/package.json": PACKAGE_JSON,
        "backend/requirements.txt": REQUIREMENTS,
        "Dockerfile": "FROM python:3.12-slim\nRUN pip install x\n",
    }
    contents.update(files or {})
    for path, text in contents.items():
        router.get(f"{base}/contents/{path}").mock(return_value=httpx.Response(200, json=b64(text)))
    return router


def requested(router) -> list[httpx.Request]:
    return [call.request for call in router.calls]
