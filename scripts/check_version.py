"""Fail unless backend, frontend (and optionally a git tag) agree on the version.

python scripts/check_version.py            # backend == frontend
python scripts/check_version.py v0.9.0     # ... == tag (release workflow)
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def versions() -> dict[str, str]:
    init = (ROOT / "backend" / "mebot" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    return {
        "backend/mebot/__init__.py": m.group(1) if m else "?",
        "frontend/package.json": pkg["version"],
    }


def main(argv: list[str]) -> int:
    found = versions()
    if argv:
        found["git tag"] = argv[0].removeprefix("refs/tags/").removeprefix("v")
    if len(set(found.values())) != 1:
        for where, v in found.items():
            print(f"  {where}: {v}", file=sys.stderr)
        print("version mismatch", file=sys.stderr)
        return 1
    print(next(iter(found.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
