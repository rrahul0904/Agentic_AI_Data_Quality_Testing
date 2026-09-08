#!/usr/bin/env python3
"""Emit a reproducible current implementation baseline."""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

from agentic_data_platform.api.app import create_app
from agentic_data_platform.providers import ProviderRegistry
from agentic_data_platform.skills import BUILTIN_SKILLS
from agentic_data_platform.tools.builtin import build_tool_registry

ROOT = Path(__file__).resolve().parents[1]


def command(args: list[str]) -> str | None:
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr).strip() else None


def main() -> int:
    registry = build_tool_registry()
    app = create_app()
    test_files = list((ROOT / "tests").rglob("test_*.py"))
    payload = {
        "python": platform.python_version(),
        "node": command(["node", "--version"]),
        "dbt": command(["dbt", "--version"]),
        "airflow": command(["airflow", "version"]),
        "tool_count": len(registry.definitions()),
        "test_file_count": len(test_files),
        "api_route_count": len([route for route in app.routes if getattr(route, "path", None)]),
        "provider_count": len(ProviderRegistry().names()),
        "skill_count": len(BUILTIN_SKILLS),
        "branch": command(["git", "branch", "--show-current"]),
        "commit": command(["git", "rev-parse", "HEAD"]),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
