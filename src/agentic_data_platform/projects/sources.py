from __future__ import annotations

"""Fail-closed project-source adapters for hosted ADE runtimes.

Hosted deployments must not depend on a developer-machine bind mount. The
filesystem adapter preserves existing local/demo behavior, while the Git adapter
materializes a bounded checkout under a managed workspace root.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Mapping
from urllib.parse import urlparse


class ProjectSourceError(RuntimeError):
    """Raised when a configured project source cannot be materialized safely."""


@dataclass(frozen=True)
class MaterializedProject:
    root: Path
    mode: str
    source_ref: str | None = None


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: int = 120) -> str:
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ProjectSourceError("git executable is required for ADE_PROJECT_SOURCE_MODE=git") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProjectSourceError("git project materialization timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "git command failed").strip()
        raise ProjectSourceError(f"git project materialization failed: {detail[-1000:]}") from exc
    return completed.stdout.strip()


def _validate_git_source(url: str, *, allow_local: bool = False) -> str:
    candidate = url.strip()
    if not candidate:
        raise ProjectSourceError("ADE_PROJECT_GIT_URL is required for git project sources")

    parsed = urlparse(candidate)
    if parsed.scheme == "https":
        if not parsed.hostname:
            raise ProjectSourceError("git source URL must include a hostname")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProjectSourceError("git source URL must not embed credentials, query parameters, or fragments")
        return candidate

    if allow_local:
        local = Path(candidate).expanduser().resolve()
        if not local.is_dir():
            raise ProjectSourceError(f"local git source does not exist: {local}")
        return str(local)

    raise ProjectSourceError("hosted git project sources must use https:// URLs")


def _validate_git_ref(ref: str | None) -> str | None:
    if ref is None:
        return None
    candidate = ref.strip()
    if not candidate:
        return None
    if len(candidate) > 256 or candidate.startswith("-") or "\x00" in candidate or "\n" in candidate or "\r" in candidate:
        raise ProjectSourceError("ADE_PROJECT_GIT_REF is invalid")
    return candidate


def _reject_project_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ProjectSourceError(f"project source contains unsupported symlink: {path.relative_to(root)}")


def _workspace_key(url: str, ref: str | None) -> str:
    material = f"{url}\0{ref or ''}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def _write_receipt(root: Path, *, url: str, ref: str | None, commit_sha: str) -> None:
    receipt_dir = root / ".ade"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "project-source.json").write_text(
        json.dumps(
            {
                "schema_version": "ade.project-source.v1",
                "mode": "git",
                "source": url,
                "requested_ref": ref,
                "commit_sha": commit_sha,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def materialize_git_project(
    url: str,
    *,
    ref: str | None = None,
    workspace_root: str | Path,
    allow_local: bool = False,
) -> MaterializedProject:
    safe_url = _validate_git_source(url, allow_local=allow_local)
    safe_ref = _validate_git_ref(ref)
    workspace = Path(workspace_root).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    target = workspace / f"project-{_workspace_key(safe_url, safe_ref)}"
    receipt = target / ".ade" / "project-source.json"
    # Only immutable/explicit refs are cacheable. An omitted ref means "current
    # default branch" and must be refreshed on each process start.
    if safe_ref and target.is_dir() and receipt.is_file():
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if (
            payload.get("mode") == "git"
            and payload.get("source") == safe_url
            and payload.get("requested_ref") == safe_ref
            and payload.get("commit_sha")
        ):
            _reject_project_symlinks(target)
            return MaterializedProject(target, "git", str(payload["commit_sha"]))

    temp_root = Path(tempfile.mkdtemp(prefix=".ade-project-", dir=workspace))
    checkout = temp_root / "checkout"
    try:
        if safe_ref:
            _run_git(["init", "--quiet", str(checkout)])
            _run_git(["remote", "add", "origin", safe_url], cwd=checkout)
            _run_git(["fetch", "--quiet", "--depth", "1", "--no-tags", "origin", safe_ref], cwd=checkout)
            _run_git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=checkout)
        else:
            _run_git(["clone", "--quiet", "--depth", "1", "--no-tags", safe_url, str(checkout)])

        commit_sha = _run_git(["rev-parse", "HEAD"], cwd=checkout)
        git_metadata = checkout / ".git"
        if git_metadata.exists():
            shutil.rmtree(git_metadata)
        _reject_project_symlinks(checkout)
        _write_receipt(checkout, url=safe_url, ref=safe_ref, commit_sha=commit_sha)

        if target.exists():
            shutil.rmtree(target)
        checkout.replace(target)
        return MaterializedProject(target, "git", commit_sha)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def resolve_hosted_project(
    env: Mapping[str, str] | None = None,
    *,
    default_project: str | Path | None = None,
) -> MaterializedProject:
    values = os.environ if env is None else env
    mode = str(values.get("ADE_PROJECT_SOURCE_MODE") or "").strip().lower()
    git_url = str(values.get("ADE_PROJECT_GIT_URL") or "").strip()

    if not mode:
        mode = "git" if git_url else "filesystem"

    if mode in {"filesystem", "embedded_demo"}:
        configured = values.get("ADE_PROJECT_ROOT") or values.get("ADE_DEMO_PROJECT")
        root_value = configured or default_project
        if not root_value:
            raise ProjectSourceError("filesystem project source requires ADE_PROJECT_ROOT or ADE_DEMO_PROJECT")
        root = Path(root_value).expanduser().resolve()
        if not root.is_dir():
            raise ProjectSourceError(f"configured project root does not exist: {root}")
        return MaterializedProject(root, mode)

    if mode == "git":
        workspace_root = values.get("ADE_WORKSPACE_ROOT") or "/workspaces"
        ref = str(values.get("ADE_PROJECT_GIT_REF") or "").strip() or None
        return materialize_git_project(git_url, ref=ref, workspace_root=workspace_root)

    raise ProjectSourceError("ADE_PROJECT_SOURCE_MODE must be one of: filesystem, embedded_demo, git")
