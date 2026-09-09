"""ADE desktop/IDE bridge with VS Code bundle, file context, edits and dev-server registry."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


def _hash(value: bytes) -> str:
    return sha256(value).hexdigest()


def _safe_relative(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("IDE path must be project-relative")
    return path


def _url(value: str) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("dev server URL must be absolute http/https")
    return str(value)


class IDEBridge:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.ade_root = self.project_root / ".ade"

    def _target(self, relative: str | Path) -> Path:
        path = (self.project_root / _safe_relative(relative)).resolve()
        if path != self.project_root and self.project_root not in path.parents:
            raise ValueError("IDE path escapes project root")
        return path

    def plan_workspace(
        self,
        *,
        console_url: str = "http://localhost:3000",
        extension_directory: str = ".ade/vscode-extension",
    ) -> dict[str, Any]:
        console = _url(console_url)
        extension_root = _safe_relative(extension_directory)
        package = {
            "name": "ade-desktop-bridge",
            "displayName": "Agentic Data Engineering OS",
            "description": "Desktop bridge for ADE sessions, runners, automations, and project navigation.",
            "version": "0.1.0",
            "engines": {"vscode": "^1.90.0"},
            "categories": ["Other"],
            "activationEvents": [
                "onCommand:ade.openConsole",
                "onCommand:ade.startHostedRunner",
                "onCommand:ade.startAutomationWorker",
            ],
            "main": "./extension.js",
            "contributes": {
                "commands": [
                    {"command": "ade.openConsole", "title": "ADE: Open Operator Console"},
                    {"command": "ade.startHostedRunner", "title": "ADE: Start Hosted Runner"},
                    {"command": "ade.startAutomationWorker", "title": "ADE: Start Automation Worker"},
                ]
            },
        }
        extension_js = (
            "const vscode = require('vscode');\n"
            "function activate(context) {\n"
            f"  const consoleUrl = {json.dumps(console)};\n"
            "  context.subscriptions.push(vscode.commands.registerCommand('ade.openConsole', () => {\n"
            "    return vscode.env.openExternal(vscode.Uri.parse(consoleUrl));\n"
            "  }));\n"
            "  context.subscriptions.push(vscode.commands.registerCommand('ade.startHostedRunner', () => {\n"
            "    const term = vscode.window.createTerminal({name: 'ADE Hosted Runner'});\n"
            "    term.sendText('python scripts/run_hosted_runner.py --project . --json');\n"
            "    term.show();\n"
            "  }));\n"
            "  context.subscriptions.push(vscode.commands.registerCommand('ade.startAutomationWorker', () => {\n"
            "    const term = vscode.window.createTerminal({name: 'ADE Automations'});\n"
            "    term.sendText('python scripts/run_automation_worker.py --project . --json');\n"
            "    term.show();\n"
            "  }));\n"
            "}\n"
            "function deactivate() {}\n"
            "module.exports = { activate, deactivate };\n"
        )
        files = {
            ".ade/ide.json": json.dumps(
                {
                    "version": 1,
                    "console_url": console,
                    "protocol": "ade-desktop-bridge/1",
                    "runner_database": ".ade/hosted-runner.db",
                    "automation_database": ".ade/automations.db",
                    "semantic_database": ".ade/semantic.db",
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            ".vscode/tasks.json": json.dumps(
                {
                    "version": "2.0.0",
                    "tasks": [
                        {
                            "label": "ADE: Hosted Runner",
                            "type": "shell",
                            "command": "python scripts/run_hosted_runner.py --project . --json",
                            "isBackground": True,
                            "problemMatcher": [],
                        },
                        {
                            "label": "ADE: Automation Worker",
                            "type": "shell",
                            "command": "python scripts/run_automation_worker.py --project . --json",
                            "isBackground": True,
                            "problemMatcher": [],
                        },
                        {
                            "label": "ADE: Verify",
                            "type": "shell",
                            "command": "make verify",
                            "problemMatcher": [],
                        },
                    ],
                },
                indent=2,
            ) + "\n",
            ".vscode/settings.json": json.dumps(
                {
                    "files.exclude": {".ade/*.db": True},
                    "search.exclude": {".ade/*.db": True},
                    "terminal.integrated.env.osx": {"ADE_PROJECT_ROOT": "${workspaceFolder}"},
                    "terminal.integrated.env.linux": {"ADE_PROJECT_ROOT": "${workspaceFolder}"},
                    "terminal.integrated.env.windows": {"ADE_PROJECT_ROOT": "${workspaceFolder}"},
                },
                indent=2,
            ) + "\n",
            ".vscode/extensions.json": json.dumps(
                {"recommendations": ["ms-python.python", "ms-python.vscode-pylance"]},
                indent=2,
            ) + "\n",
            (extension_root / "package.json").as_posix(): json.dumps(package, indent=2) + "\n",
            (extension_root / "extension.js").as_posix(): extension_js,
            (extension_root / "README.md").as_posix(): (
                "# Agentic Data Engineering OS VS Code Bridge\n\n"
                "This project-scoped extension exposes the ADE operator console and worker commands. "
                "All data/warehouse mutations still execute through ADE ToolRegistry policy.\n"
            ),
        }
        fingerprint = _hash(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        return {
            "status": "PASS",
            "approval_fingerprint": fingerprint,
            "files": files,
            "console_url": console,
            "extension_directory": extension_root.as_posix(),
        }

    def apply_workspace(
        self,
        plan: dict[str, Any],
        *,
        approval_fingerprint: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        files = {str(key): str(value) for key, value in dict(plan.get("files") or {}).items()}
        expected = _hash(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if approval_fingerprint != expected or plan.get("approval_fingerprint") != expected:
            return {"status": "BLOCKED_APPROVAL", "reason": "IDE workspace plan fingerprint mismatch"}
        written = []
        for relative, content in dict(plan.get("files") or {}).items():
            target = self._target(relative)
            if target.exists() and not overwrite and target.read_text() != str(content):
                raise FileExistsError(f"IDE workspace file already exists with different content: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content))
            written.append(relative)
        verified = all(self._target(path).read_text() == content for path, content in plan["files"].items())
        return {
            "status": "PASS" if verified else "FAIL",
            "verified": verified,
            "written": written,
            "approval_fingerprint": approval_fingerprint,
        }

    def context(
        self,
        path: str,
        *,
        line: int = 1,
        radius: int = 30,
        max_bytes: int = 100_000,
    ) -> dict[str, Any]:
        target = self._target(path)
        raw = target.read_bytes()
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        center = max(1, int(line))
        radius = max(0, min(int(radius), 500))
        start = max(1, center - radius)
        end = min(len(lines), center + radius)
        return {
            "status": "PASS",
            "path": path,
            "fingerprint": _hash(target.read_bytes()),
            "start_line": start,
            "end_line": end,
            "lines": [
                {"line": index, "text": lines[index - 1]}
                for index in range(start, end + 1)
            ],
        }

    def open_target(self, path: str, *, line: int = 1, column: int = 1) -> dict[str, Any]:
        target = self._target(path)
        line = max(1, int(line))
        column = max(1, int(column))
        encoded = quote(target.as_posix(), safe="/:")
        return {
            "status": "PASS",
            "path": path,
            "line": line,
            "column": column,
            "vscode_uri": f"vscode://file/{encoded}:{line}:{column}",
            "file_uri": target.as_uri(),
        }

    def plan_edit(self, path: str, replacements: list[dict[str, Any]]) -> dict[str, Any]:
        target = self._target(path)
        raw = target.read_bytes()
        source_hash = _hash(raw)
        text = raw.decode("utf-8")
        lines = text.splitlines(keepends=True)
        normalized = []
        for item in replacements:
            start = int(item["start_line"])
            end = int(item.get("end_line", start))
            if start < 1 or end < start or end > max(1, len(lines)):
                raise ValueError(f"invalid edit line range: {start}-{end}")
            normalized.append({
                "start_line": start,
                "end_line": end,
                "text": str(item.get("text") or ""),
            })
        normalized.sort(key=lambda item: item["start_line"])
        for left, right in zip(normalized, normalized[1:], strict=False):
            if right["start_line"] <= left["end_line"]:
                raise ValueError("IDE edit ranges may not overlap")

        updated = list(lines)
        for item in reversed(normalized):
            replacement = item["text"].splitlines(keepends=True)
            if item["text"] and not item["text"].endswith("\n") and item["end_line"] < len(lines):
                replacement[-1] += "\n"
            updated[item["start_line"] - 1:item["end_line"]] = replacement
        result = "".join(updated)
        result_hash = _hash(result.encode("utf-8"))
        approval = _hash(f"{path}|{source_hash}|{result_hash}".encode("utf-8"))
        return {
            "status": "PASS",
            "path": path,
            "source_fingerprint": source_hash,
            "result_fingerprint": result_hash,
            "approval_fingerprint": approval,
            "replacements": normalized,
            "result": result,
        }

    def apply_edit(
        self,
        path: str,
        replacements: list[dict[str, Any]],
        *,
        approval_fingerprint: str,
    ) -> dict[str, Any]:
        plan = self.plan_edit(path, replacements)
        if plan["approval_fingerprint"] != approval_fingerprint:
            return {
                **{k: v for k, v in plan.items() if k != "result"},
                "status": "BLOCKED_APPROVAL",
                "reason": "file changed or edit no longer matches approved fingerprint",
            }
        target = self._target(path)
        target.write_text(plan["result"])
        verified = _hash(target.read_bytes()) == plan["result_fingerprint"]
        return {
            **{k: v for k, v in plan.items() if k != "result"},
            "status": "PASS" if verified else "FAIL",
            "verified": verified,
        }

    @property
    def servers_path(self) -> Path:
        return self.ade_root / "ide-servers.json"

    def _servers(self) -> dict[str, Any]:
        if not self.servers_path.is_file():
            return {"version": 1, "servers": {}}
        data = json.loads(self.servers_path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
            raise ValueError("invalid IDE dev server registry")
        return data

    def register_server(
        self,
        *,
        name: str,
        url: str,
        pid: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._servers()
        data["servers"][str(name)] = {
            "url": _url(url),
            "pid": int(pid) if pid is not None else None,
            "metadata": dict(metadata or {}),
        }
        self.servers_path.parent.mkdir(parents=True, exist_ok=True)
        self.servers_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        return {"status": "PASS", "name": name, **data["servers"][str(name)]}

    def list_servers(self) -> dict[str, Any]:
        return {"status": "PASS", **self._servers()}

    def remove_server(self, name: str) -> dict[str, Any]:
        data = self._servers()
        removed = data["servers"].pop(str(name), None)
        self.servers_path.parent.mkdir(parents=True, exist_ok=True)
        self.servers_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        return {"status": "PASS", "name": name, "removed": removed is not None}
