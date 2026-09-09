"""Governed workspace file operations for CoCo file-tool parity."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

from agentic_data_platform.advanced_capabilities import run_command


_MISSING = "MISSING"


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_text(value: str) -> str:
    return _hash_bytes(value.encode("utf-8"))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _root(workspace: str | Path) -> Path:
    value = Path(workspace).expanduser().resolve()
    value.mkdir(parents=True, exist_ok=True)
    return value


def _path(workspace: str | Path, path: str | Path) -> Path:
    root = _root(workspace)
    candidate = (root / Path(path)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes the governed workspace") from exc
    return candidate


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "sha256": _MISSING, "size": 0}
    if not path.is_file():
        raise ValueError(f"path is not a regular file: {path}")
    raw = path.read_bytes()
    return {"exists": True, "sha256": _hash_bytes(raw), "size": len(raw)}


def workspace_file_read(
    workspace: str | Path,
    path: str,
    *,
    max_bytes: int = 1_000_000,
) -> dict[str, Any]:
    root = _root(workspace)
    target = _path(root, path)
    if not target.exists() or not target.is_file():
        return {"status": "NOT_FOUND", "path": path}
    cap = max(1024, min(int(max_bytes), 10_000_000))
    raw = target.read_bytes()
    truncated = len(raw) > cap
    selected = raw[:cap]
    return {
        "status": "PASS",
        "path": _relative(root, target),
        "content": selected.decode("utf-8", errors="replace"),
        "sha256": _hash_bytes(raw),
        "size": len(raw),
        "truncated": truncated,
    }


def workspace_file_glob(
    workspace: str | Path,
    pattern: str = "**/*",
    *,
    limit: int = 1000,
    include_internal: bool = False,
) -> dict[str, Any]:
    root = _root(workspace)
    results: list[dict[str, Any]] = []
    for path in root.glob(pattern):
        try:
            relative = _relative(root, path.resolve(strict=False))
        except ValueError:
            continue
        parts = Path(relative).parts
        if not include_internal and parts and parts[0] in {".git", ".ade"}:
            continue
        if path.is_file():
            state = _file_state(path.resolve())
            results.append({"path": relative, **state})
        if len(results) >= max(1, min(int(limit), 10000)):
            break
    results.sort(key=lambda item: item["path"])
    return {
        "status": "PASS",
        "pattern": pattern,
        "files": results,
        "count": len(results),
        "listing_fingerprint": _digest([(item["path"], item["sha256"]) for item in results]),
    }


def workspace_file_find(
    workspace: str | Path,
    query: str,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    needle = str(query).casefold().strip()
    listing = workspace_file_glob(workspace, "**/*", limit=10000)
    matches = [
        item
        for item in listing["files"]
        if needle in Path(item["path"]).name.casefold() or needle in item["path"].casefold()
    ][: max(1, int(limit))]
    return {
        "status": "PASS",
        "query": query,
        "matches": matches,
        "count": len(matches),
        "search_fingerprint": _digest([(item["path"], item["sha256"]) for item in matches]),
    }


def workspace_file_grep(
    workspace: str | Path,
    pattern: str,
    *,
    file_glob: str = "**/*",
    regex: bool = False,
    case_sensitive: bool = False,
    max_matches: int = 500,
    max_file_bytes: int = 2_000_000,
) -> dict[str, Any]:
    import re

    root = _root(workspace)
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern if regex else re.escape(pattern), flags)
    matches: list[dict[str, Any]] = []
    listing = workspace_file_glob(root, file_glob, limit=10000)
    for item in listing["files"]:
        target = _path(root, item["path"])
        if item["size"] > max_file_bytes:
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = compiled.search(line)
            if match:
                matches.append(
                    {
                        "path": item["path"],
                        "line": line_number,
                        "column": match.start() + 1,
                        "text": line[:2000],
                        "file_sha256": item["sha256"],
                    }
                )
                if len(matches) >= max(1, min(int(max_matches), 5000)):
                    break
        if len(matches) >= max(1, min(int(max_matches), 5000)):
            break
    return {
        "status": "PASS",
        "pattern": pattern,
        "regex": bool(regex),
        "matches": matches,
        "count": len(matches),
        "evidence_fingerprint": _digest(matches),
    }


def workspace_file_diff(
    workspace: str | Path,
    path: str,
    *,
    proposed_content: str,
) -> dict[str, Any]:
    root = _root(workspace)
    target = _path(root, path)
    current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    current_hash = _hash_text(current) if target.exists() else _MISSING
    proposed_hash = _hash_text(proposed_content)
    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            proposed_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    return {
        "status": "PASS",
        "path": _relative(root, target),
        "source_hash": current_hash,
        "result_hash": proposed_hash,
        "changed": current_hash != proposed_hash,
        "diff": diff,
        "diff_fingerprint": _hash_text(diff),
    }


def _mutated_content(
    operation: str,
    *,
    source: str,
    content: str | None,
    old_text: str | None,
    new_text: str | None,
) -> str | None:
    if operation in {"create", "write"}:
        if content is None:
            raise ValueError("content is required")
        return str(content)
    if operation == "patch":
        if old_text is None or new_text is None:
            raise ValueError("old_text and new_text are required for patch")
        occurrences = source.count(old_text)
        if occurrences != 1:
            raise ValueError(f"patch old_text must match exactly once; found {occurrences}")
        return source.replace(old_text, new_text, 1)
    if operation == "delete":
        return None
    return source


def workspace_file_plan(
    workspace: str | Path,
    operation: str,
    path: str,
    *,
    content: str | None = None,
    destination: str | None = None,
    old_text: str | None = None,
    new_text: str | None = None,
    expected_source_hash: str | None = None,
    verification_command: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    root = _root(workspace)
    op = str(operation).casefold().replace("-", "_")
    if op == "rename":
        op = "move"
    if op not in {"create", "write", "patch", "delete", "move"}:
        raise ValueError("operation must be create, write, patch, delete, move, or rename")
    target = _path(root, path)
    source_state = _file_state(target)
    if expected_source_hash and source_state["sha256"] != expected_source_hash:
        return {
            "status": "STALE_SOURCE",
            "path": _relative(root, target),
            "source_hash": source_state["sha256"],
        }
    if op == "create" and source_state["exists"]:
        return {"status": "ALREADY_EXISTS", "path": _relative(root, target)}
    if op in {"write", "patch", "delete", "move"} and not source_state["exists"]:
        return {"status": "NOT_FOUND", "path": _relative(root, target)}

    destination_path: Path | None = None
    destination_state: dict[str, Any] | None = None
    if op == "move":
        if not destination:
            raise ValueError("destination is required for move/rename")
        destination_path = _path(root, destination)
        destination_state = _file_state(destination_path)
        if destination_state["exists"]:
            return {"status": "DESTINATION_EXISTS", "destination": _relative(root, destination_path)}

    source_text = target.read_text(encoding="utf-8", errors="replace") if source_state["exists"] else ""
    result_text = _mutated_content(
        op,
        source=source_text,
        content=content,
        old_text=old_text,
        new_text=new_text,
    )
    result_hash = (
        source_state["sha256"]
        if op == "move"
        else _MISSING if result_text is None
        else _hash_text(result_text)
    )
    diff = ""
    if op in {"create", "write", "patch", "delete"}:
        diff = "".join(
            difflib.unified_diff(
                source_text.splitlines(keepends=True),
                (result_text or "").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile="/dev/null" if op == "delete" else f"b/{path}",
            )
        )
    payload = {
        "operation": op,
        "path": _relative(root, target),
        "destination": _relative(root, destination_path) if destination_path else None,
        "source_hash": source_state["sha256"],
        "destination_hash": destination_state["sha256"] if destination_state else None,
        "result_hash": result_hash,
        "content_hash": _hash_text(content) if content is not None else None,
        "old_text_hash": _hash_text(old_text) if old_text is not None else None,
        "new_text_hash": _hash_text(new_text) if new_text is not None else None,
        "verification_command": list(verification_command) if verification_command and not isinstance(verification_command, str) else verification_command,
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "diff": diff,
        "diff_fingerprint": _hash_text(diff),
        "approval_fingerprint": _digest(payload),
        "rollback_required": True,
    }


def _backup_path(root: Path, fingerprint: str, role: str) -> Path:
    return root / ".ade" / "rollback" / "files" / fingerprint / role


def _snapshot(path: Path, backup: Path) -> dict[str, Any]:
    state = _file_state(path)
    if state["exists"]:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    return state


def workspace_file_undo(
    workspace: str | Path,
    approval_fingerprint: str,
) -> dict[str, Any]:
    root = _root(workspace)
    directory = root / ".ade" / "rollback" / "files" / approval_fingerprint
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        return {"status": "NOT_FOUND", "approval_fingerprint": approval_fingerprint}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = _path(root, manifest["path"])
    destination = _path(root, manifest["destination"]) if manifest.get("destination") else None
    source_backup = directory / "source"
    destination_backup = directory / "destination"

    if manifest["source_before"]["exists"]:
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_backup, source)
    elif source.exists():
        source.unlink()

    if destination is not None:
        if manifest["destination_before"]["exists"]:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination_backup, destination)
        elif destination.exists():
            destination.unlink()

    return {
        "status": "PASS",
        "approval_fingerprint": approval_fingerprint,
        "path": manifest["path"],
        "destination": manifest.get("destination"),
        "source_restored_hash": _file_state(source)["sha256"],
        "destination_restored_hash": _file_state(destination)["sha256"] if destination else None,
    }


def workspace_file_apply(
    workspace: str | Path,
    operation: str,
    path: str,
    *,
    approval_fingerprint: str,
    content: str | None = None,
    destination: str | None = None,
    old_text: str | None = None,
    new_text: str | None = None,
    expected_source_hash: str | None = None,
    verification_command: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    root = _root(workspace)
    plan = workspace_file_plan(
        root,
        operation,
        path,
        content=content,
        destination=destination,
        old_text=old_text,
        new_text=new_text,
        expected_source_hash=expected_source_hash,
        verification_command=verification_command,
    )
    if plan["status"] != "PASS":
        return plan
    if approval_fingerprint != plan["approval_fingerprint"]:
        return {**plan, "status": "STALE_APPROVAL"}

    target = _path(root, plan["path"])
    destination_path = _path(root, plan["destination"]) if plan.get("destination") else None
    directory = root / ".ade" / "rollback" / "files" / approval_fingerprint
    directory.mkdir(parents=True, exist_ok=True)
    source_before = _snapshot(target, directory / "source")
    destination_before = (
        _snapshot(destination_path, directory / "destination")
        if destination_path is not None
        else {"exists": False, "sha256": _MISSING, "size": 0}
    )
    manifest = {
        "path": plan["path"],
        "destination": plan.get("destination"),
        "source_before": source_before,
        "destination_before": destination_before,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    op = plan["operation"]
    if op == "move":
        assert destination_path is not None
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target.rename(destination_path)
    elif op == "delete":
        target.unlink()
    else:
        source = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        result = _mutated_content(
            op,
            source=source,
            content=content,
            old_text=old_text,
            new_text=new_text,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result or "", encoding="utf-8")

    verification = None
    if verification_command:
        verification = run_command(root, verification_command)
        if verification["status"] != "PASS":
            rollback = workspace_file_undo(root, approval_fingerprint)
            return {
                "status": "VERIFICATION_FAILED_ROLLED_BACK",
                "approval_fingerprint": approval_fingerprint,
                "verification": verification,
                "rollback": rollback,
            }

    resulting_path = destination_path if op == "move" else target
    result_state = _file_state(resulting_path)
    expected_hash = plan["result_hash"]
    if result_state["sha256"] != expected_hash:
        rollback = workspace_file_undo(root, approval_fingerprint)
        return {
            "status": "VERIFY_FAILED_ROLLED_BACK",
            "expected_hash": expected_hash,
            "actual_hash": result_state["sha256"],
            "rollback": rollback,
        }
    return {
        "status": "PASS",
        "operation": op,
        "path": plan["path"],
        "destination": plan.get("destination"),
        "source_hash": plan["source_hash"],
        "result_hash": result_state["sha256"],
        "diff": plan["diff"],
        "approval_fingerprint": approval_fingerprint,
        "verification": verification,
        "undo_available": True,
    }
