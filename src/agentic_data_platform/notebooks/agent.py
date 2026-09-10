"""Notebook agent primitives: inspect, patch, deploy and execute."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _load(path: str | Path) -> tuple[Path, dict[str, Any], str]:
    target = Path(path).expanduser().resolve()
    if target.suffix.casefold() != ".ipynb":
        raise ValueError("notebook path must end in .ipynb")
    raw = target.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        raise ValueError("invalid notebook document")
    return target, data, _hash_bytes(raw)


def _source_text(cell: dict[str, Any]) -> str:
    source = cell.get("source") or []
    return "".join(source) if isinstance(source, list) else str(source)


def _source_lines(text: str) -> list[str]:
    return str(text).splitlines(keepends=True) or [""]


class NotebookAgent:
    def inspect(self, path: str | Path) -> dict[str, Any]:
        target, data, fingerprint = _load(path)
        cells = []
        for index, cell in enumerate(data["cells"]):
            metadata = dict(cell.get("metadata") or {})
            text = _source_text(cell)
            language = (
                metadata.get("language")
                or metadata.get("vscode", {}).get("languageId")
                or metadata.get("snowflake", {}).get("language")
            )
            cells.append({
                "index": index,
                "cell_type": cell.get("cell_type"),
                "language": language,
                "line_count": len(text.splitlines()),
                "preview": text[:500],
                "tags": list(metadata.get("tags") or []),
                "execution_count": cell.get("execution_count"),
                "has_outputs": bool(cell.get("outputs")),
            })
        return {
            "status": "PASS",
            "path": str(target),
            "fingerprint": fingerprint,
            "kernel": (data.get("metadata") or {}).get("kernelspec"),
            "cell_count": len(cells),
            "cells": cells,
        }

    def plan_create(
        self,
        path: str | Path,
        cells: list[dict[str, Any]],
        *,
        kernel_name: str = "python3",
        display_name: str = "Python 3",
        language: str = "python",
    ) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if target.suffix.casefold() != ".ipynb":
            raise ValueError("notebook path must end in .ipynb")
        rendered_cells: list[dict[str, Any]] = []
        for index, item in enumerate(cells):
            if not isinstance(item, dict):
                raise ValueError(f"notebook cell {index} must be an object")
            cell_type = str(item.get("cell_type") or "code").casefold()
            if cell_type not in {"code", "markdown", "raw"}:
                raise ValueError("cell_type must be code, markdown, or raw")
            cell: dict[str, Any] = {
                "cell_type": cell_type,
                "metadata": dict(item.get("metadata") or {}),
                "source": _source_lines(str(item.get("source") or "")),
            }
            if cell_type == "code":
                cell["metadata"].setdefault("vscode", {"languageId": language})
                cell.update({"execution_count": None, "outputs": []})
            rendered_cells.append(cell)
        notebook = {
            "cells": rendered_cells,
            "metadata": {
                "kernelspec": {
                    "display_name": str(display_name),
                    "language": str(language),
                    "name": str(kernel_name),
                },
                "language_info": {"name": str(language)},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        rendered = json.dumps(notebook, indent=1, ensure_ascii=False).encode("utf-8") + b"\n"
        result_fingerprint = _hash_bytes(rendered)
        approval_fingerprint = sha256(
            (str(target) + "|" + result_fingerprint).encode("utf-8")
        ).hexdigest()
        return {
            "status": "PASS",
            "path": str(target),
            "approval_fingerprint": approval_fingerprint,
            "result_fingerprint": result_fingerprint,
            "cell_count": len(rendered_cells),
            "kernel": notebook["metadata"]["kernelspec"],
            "notebook": notebook,
        }

    def apply_create(
        self,
        path: str | Path,
        cells: list[dict[str, Any]],
        *,
        approval_fingerprint: str,
        overwrite: bool = False,
        kernel_name: str = "python3",
        display_name: str = "Python 3",
        language: str = "python",
    ) -> dict[str, Any]:
        plan = self.plan_create(
            path,
            cells,
            kernel_name=kernel_name,
            display_name=display_name,
            language=language,
        )
        if approval_fingerprint != plan["approval_fingerprint"]:
            return {
                **{k: v for k, v in plan.items() if k != "notebook"},
                "status": "BLOCKED_APPROVAL",
                "reason": "notebook creation does not match approved fingerprint",
            }
        target = Path(plan["path"])
        if target.exists() and not overwrite:
            raise FileExistsError(f"notebook already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(plan["notebook"], indent=1, ensure_ascii=False) + "\n")
        verified = _hash_bytes(target.read_bytes()) == plan["result_fingerprint"]
        return {
            **{k: v for k, v in plan.items() if k != "notebook"},
            "status": "PASS" if verified else "FAIL",
            "verified": verified,
        }

    @staticmethod
    def run_local(
        path: str | Path,
        *,
        timeout_seconds: int = 900,
    ) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if target.suffix.casefold() != ".ipynb":
            raise ValueError("notebook path must end in .ipynb")
        if not target.is_file():
            raise FileNotFoundError(target)
        command = [
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            str(target),
            f"--ExecutePreprocessor.timeout={max(1, int(timeout_seconds))}",
        ]
        if shutil.which("jupyter") is None:
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "Jupyter executable is not installed",
                "command": command,
            }
        before = _hash_bytes(target.read_bytes())
        process = subprocess.run(
            command,
            cwd=target.parent,
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_seconds)) + 30,
            check=False,
        )
        after = _hash_bytes(target.read_bytes()) if target.is_file() else None
        return {
            "status": "PASS" if process.returncode == 0 else "FAIL",
            "returncode": process.returncode,
            "stdout": process.stdout[-8000:],
            "stderr": process.stderr[-8000:],
            "command": command,
            "source_fingerprint": before,
            "result_fingerprint": after,
            "executed": process.returncode == 0,
        }

    def plan_patch(
        self,
        path: str | Path,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        target, data, fingerprint = _load(path)
        updated = deepcopy(data)
        cells = updated["cells"]
        applied = []
        for operation in operations:
            action = str(operation.get("action") or "").casefold()
            index = int(operation.get("index", -1))
            if action == "replace":
                if not 0 <= index < len(cells):
                    raise IndexError(f"notebook cell index out of range: {index}")
                before = _source_text(cells[index])
                cells[index]["source"] = _source_lines(str(operation.get("source") or ""))
                applied.append({"action": action, "index": index, "before": before[:500]})
            elif action == "insert":
                if not 0 <= index <= len(cells):
                    raise IndexError(f"notebook insert index out of range: {index}")
                cell_type = str(operation.get("cell_type") or "code")
                if cell_type not in {"code", "markdown", "raw"}:
                    raise ValueError("cell_type must be code, markdown, or raw")
                cell = {
                    "cell_type": cell_type,
                    "metadata": dict(operation.get("metadata") or {}),
                    "source": _source_lines(str(operation.get("source") or "")),
                }
                if cell_type == "code":
                    cell.update({"execution_count": None, "outputs": []})
                cells.insert(index, cell)
                applied.append({"action": action, "index": index})
            elif action == "delete":
                if not 0 <= index < len(cells):
                    raise IndexError(f"notebook cell index out of range: {index}")
                removed = cells.pop(index)
                applied.append({"action": action, "index": index, "before": _source_text(removed)[:500]})
            else:
                raise ValueError(f"unsupported notebook patch action: {action}")

        rendered = json.dumps(updated, indent=1, ensure_ascii=False).encode("utf-8") + b"\n"
        return {
            "status": "PASS",
            "path": str(target),
            "approval_fingerprint": sha256(
                (fingerprint + "|" + _hash_bytes(rendered)).encode("utf-8")
            ).hexdigest(),
            "source_fingerprint": fingerprint,
            "result_fingerprint": _hash_bytes(rendered),
            "operations": applied,
            "notebook": updated,
        }

    def apply_patch(
        self,
        path: str | Path,
        operations: list[dict[str, Any]],
        *,
        approval_fingerprint: str,
    ) -> dict[str, Any]:
        plan = self.plan_patch(path, operations)
        if approval_fingerprint != plan["approval_fingerprint"]:
            return {
                **{k: v for k, v in plan.items() if k != "notebook"},
                "status": "BLOCKED_APPROVAL",
                "reason": "notebook changed or patch does not match approved fingerprint",
            }
        target = Path(plan["path"])
        target.write_text(json.dumps(plan["notebook"], indent=1, ensure_ascii=False) + "\n")
        verified = _hash_bytes(target.read_bytes()) == plan["result_fingerprint"]
        return {
            **{k: v for k, v in plan.items() if k != "notebook"},
            "status": "PASS" if verified else "FAIL",
            "verified": verified,
        }

    @staticmethod
    def snowflake_command(
        action: str,
        *,
        identifier: str,
        project_definition: str | None = None,
        connection: str | None = None,
    ) -> list[str]:
        action = str(action).casefold()
        if action not in {"deploy", "execute"}:
            raise ValueError("notebook Snowflake action must be deploy or execute")
        command = ["snow", "notebook", action, str(identifier)]
        if project_definition:
            command += ["--project", str(project_definition)]
        if connection:
            command += ["--connection", str(connection)]
        return command

    @staticmethod
    def run_snowflake(
        action: str,
        *,
        identifier: str,
        cwd: str | Path,
        project_definition: str | None = None,
        connection: str | None = None,
        timeout_seconds: int = 900,
    ) -> dict[str, Any]:
        command = NotebookAgent.snowflake_command(
            action,
            identifier=identifier,
            project_definition=project_definition,
            connection=connection,
        )
        if shutil.which("snow") is None:
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "Snowflake CLI executable 'snow' is not installed",
                "command": command,
            }
        process = subprocess.run(
            command,
            cwd=Path(cwd).expanduser().resolve(),
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
        return {
            "status": "PASS" if process.returncode == 0 else "FAIL",
            "returncode": process.returncode,
            "stdout": process.stdout[-8000:],
            "stderr": process.stderr[-8000:],
            "command": command,
        }
