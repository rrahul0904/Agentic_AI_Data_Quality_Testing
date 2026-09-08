#!/usr/bin/env python3
"""Inventory the pinned Altimate reference tree from GitHub or a local reference clone."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_SHA = "ec475f46ba0a4ce6bcfbed33cebacf31ad45a455"


def classify(paths: list[str]) -> dict[str, int]:
    return {
        "tools": sum(p.startswith("packages/opencode/src/altimate/tools/") and p.endswith(".ts") for p in paths),
        "native": sum(p.startswith("packages/opencode/src/altimate/native/") and p.endswith(".ts") for p in paths),
        "session": sum(p.startswith("packages/opencode/src/session/") and p.endswith(".ts") for p in paths),
        "provider": sum(p.startswith("packages/opencode/src/provider/") and p.endswith(".ts") for p in paths),
        "mcp": sum(p.startswith("packages/opencode/src/mcp/") and p.endswith(".ts") for p in paths),
        "skills": sum(p.startswith(".opencode/skills/") and p.endswith("/SKILL.md") for p in paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", default=DEFAULT_SHA)
    parser.add_argument("--reference-root")
    args = parser.parse_args()
    if args.reference_root:
        root = Path(args.reference_root)
        paths = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]
        source = str(root)
    else:
        request = Request(
            f"https://api.github.com/repos/AltimateAI/altimate-code/git/trees/{args.sha}?recursive=1",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "agentic-data-platform-parity"},
        )
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API endpoint
            payload = json.load(response)
        paths = [item["path"] for item in payload.get("tree", []) if item.get("type") == "blob"]
        source = "github"
    print(json.dumps({"repository": "AltimateAI/altimate-code", "sha": args.sha, "source": source, "counts": classify(paths)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
