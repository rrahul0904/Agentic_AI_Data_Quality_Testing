#!/usr/bin/env python3
"""Run real GitHub/GitLab review delivery only when external configuration exists."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agentic_data_platform.review.e2e import run_github_review_e2e, run_gitlab_review_e2e


def _skip(provider: str, reason: str) -> int:
    print(json.dumps({"status": "SKIP_EXTERNAL", "provider": provider, "reason": reason}, indent=2))
    return 0


def main() -> int:
    provider = os.getenv("ADE_REVIEW_PROVIDER", "github").casefold()
    project_dir = Path(os.getenv("ADE_REVIEW_PROJECT_DIR", "hospitality-snowflake-data-platform/dbt")).resolve()
    target_dir = Path(os.getenv("ADE_REVIEW_TARGET_DIR", str(project_dir / "target"))).resolve()
    if provider == "github":
        repository = os.getenv("ADE_REVIEW_GITHUB_REPOSITORY") or os.getenv("GITHUB_REPOSITORY")
        pull = os.getenv("ADE_REVIEW_GITHUB_PR_NUMBER")
        if not os.getenv("ADE_REVIEW_GITHUB_TOKEN"):
            return _skip(provider, "ADE_REVIEW_GITHUB_TOKEN is not configured")
        if not repository or not pull:
            return _skip(provider, "ADE_REVIEW_GITHUB_REPOSITORY and ADE_REVIEW_GITHUB_PR_NUMBER are required")
        result = run_github_review_e2e(
            project_dir,
            target_dir=target_dir,
            repository=repository,
            pull_number=int(pull),
            token_env="ADE_REVIEW_GITHUB_TOKEN",
            api_url=os.getenv("ADE_REVIEW_GITHUB_API_URL", "https://api.github.com"),
        )
    elif provider == "gitlab":
        project = os.getenv("ADE_REVIEW_GITLAB_PROJECT")
        mr = os.getenv("ADE_REVIEW_GITLAB_MR_IID")
        if not os.getenv("ADE_REVIEW_GITLAB_TOKEN"):
            return _skip(provider, "ADE_REVIEW_GITLAB_TOKEN is not configured")
        if not project or not mr:
            return _skip(provider, "ADE_REVIEW_GITLAB_PROJECT and ADE_REVIEW_GITLAB_MR_IID are required")
        result = run_gitlab_review_e2e(
            project_dir,
            target_dir=target_dir,
            project=project,
            merge_request_iid=int(mr),
            token_env="ADE_REVIEW_GITLAB_TOKEN",
            api_url=os.getenv("ADE_REVIEW_GITLAB_API_URL", "https://gitlab.com/api/v4"),
        )
    else:
        raise SystemExit(f"unsupported ADE_REVIEW_PROVIDER: {provider}")
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in {"PASS", "SKIP_EXTERNAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
