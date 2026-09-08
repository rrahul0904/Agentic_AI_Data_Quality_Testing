"""Governed user-feedback submission through the GitHub CLI."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Any, Callable


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_CATEGORY_LABELS = {
    "bug": "bug",
    "feature": "enhancement",
    "improvement": "improvement",
    "ux": "ux",
}


def _runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def submit_feedback(
    *,
    title: str,
    category: str,
    description: str,
    include_context: bool = False,
    repository: str = "rrahul0904/Agentic_AI_Data_Quality_Testing",
    session_id: str | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("feedback title is required")
    if not description.strip():
        raise ValueError("feedback description is required")
    if category not in _CATEGORY_LABELS:
        raise ValueError(f"invalid feedback category: {category}")
    run = runner or _runner

    try:
        version = run(["gh", "--version"])
    except FileNotFoundError:
        return {
            "status": "SKIP_EXTERNAL",
            "error": "gh_not_installed",
            "issue_url": "",
        }
    if version.returncode != 0 or not version.stdout.strip().startswith("gh version"):
        return {
            "status": "SKIP_EXTERNAL",
            "error": "gh_not_installed",
            "issue_url": "",
        }

    auth = run(["gh", "auth", "status"])
    if auth.returncode != 0:
        return {
            "status": "SKIP_EXTERNAL",
            "error": "gh_not_authenticated",
            "issue_url": "",
        }

    body = description.strip() + "\n\n---\n\n### Metadata\n\n"
    body += f"- Platform: {platform.system()}\n"
    body += f"- Architecture: {platform.machine()}\n"
    body += f"- OS release: {platform.release()}\n"
    body += f"- Category: {category}\n"
    if include_context:
        body += f"- Working directory: {Path.cwd().name or 'unknown'}\n"
        if session_id:
            body += f"- Session ID: {session_id}\n"

    labels = f"user-feedback,from-cli,{_CATEGORY_LABELS[category]}"
    args = [
        "gh",
        "issue",
        "create",
        "--repo",
        repository,
        "--title",
        title.strip(),
        "--body",
        body,
        "--label",
        labels,
    ]
    result = run(args)
    if result.returncode != 0 or "github.com" not in result.stdout:
        fallback = run(args[:-2])
        result = fallback
    if result.returncode != 0:
        return {
            "status": "FAIL",
            "error": "issue_creation_failed",
            "detail": (result.stderr or result.stdout)[-2000:],
            "issue_url": "",
        }
    issue_url = result.stdout.strip().splitlines()[-1].strip()
    return {
        "status": "PASS",
        "repository": repository,
        "issue_url": issue_url,
        "category": category,
    }
