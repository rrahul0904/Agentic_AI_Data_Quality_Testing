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
        api_url: str = "http://localhost:8000",
        extension_directory: str = ".ade/vscode-extension",
    ) -> dict[str, Any]:
        console = _url(console_url)
        api = _url(api_url).rstrip("/")
        extension_root = _safe_relative(extension_directory)
        commands = [
            {"command": "ade.openConsole", "title": "ADE: Open Operator Console"},
            {"command": "ade.listSessions", "title": "ADE: Browse Sessions"},
            {"command": "ade.reviewCheckpoint", "title": "ADE: Review Session Checkpoints"},
            {"command": "ade.showCurrentContext", "title": "ADE: Show Current File Context"},
            {"command": "ade.planSelectedEdit", "title": "ADE: Plan Selected Edit"},
            {"command": "ade.startHostedRunner", "title": "ADE: Start Hosted Runner"},
            {"command": "ade.startAutomationWorker", "title": "ADE: Start Automation Worker"},
        ]
        package = {
            "name": "ade-desktop-bridge",
            "displayName": "Agentic Data Engineering OS",
            "description": (
                "Governed ADE bridge for sessions, checkpoint evidence, file context, "
                "edit planning, runners and automations."
            ),
            "version": "0.2.0",
            "engines": {"vscode": "^1.90.0"},
            "categories": ["Other"],
            "activationEvents": [f"onCommand:{item['command']}" for item in commands],
            "main": "./extension.js",
            "contributes": {"commands": commands},
        }
        extension_js = f"""const vscode = require('vscode');

function activate(context) {{
  const consoleUrl = {json.dumps(console)};
  const apiUrl = {json.dumps(api)};
  async function request(path, options = {{}}) {{
    const response = await fetch(apiUrl + path, options);
    const text = await response.text();
    let payload = {{}};
    try {{ payload = text ? JSON.parse(text) : {{}}; }} catch (_) {{ payload = {{raw: text}}; }}
    if (!response.ok) {{
      throw new Error(payload.detail || payload.error || ('HTTP ' + response.status));
    }}
    return payload;
  }}
  async function showJson(title, payload) {{
    const document = await vscode.workspace.openTextDocument({{
      content: JSON.stringify(payload, null, 2),
      language: 'json',
    }});
    await vscode.window.showTextDocument(document, {{preview: true}});
    vscode.window.setStatusBarMessage(title, 3000);
  }}
  function activeLocation() {{
    const editor = vscode.window.activeTextEditor;
    if (!editor) throw new Error('Open a workspace file first.');
    const path = vscode.workspace.asRelativePath(editor.document.uri, false);
    if (!path || path.startsWith('..')) throw new Error('File must be inside the ADE workspace.');
    return {{editor, path}};
  }}
  function readPayload(args, actorMode = 'analyst') {{
    return JSON.stringify({{
      args,
      actor_mode: actorMode,
      environment: 'dev',
      approved: false,
      dry_run: false,
    }});
  }}

  context.subscriptions.push(vscode.commands.registerCommand('ade.openConsole', async () => {{
    await vscode.env.openExternal(vscode.Uri.parse(consoleUrl));
  }}));

  context.subscriptions.push(vscode.commands.registerCommand('ade.listSessions', async () => {{
    try {{
      const payload = await request('/api/v1/sessions');
      const sessions = Array.isArray(payload) ? payload : (payload.sessions || []);
      if (!sessions.length) {{
        vscode.window.showInformationMessage('ADE: no persisted sessions found.');
        return;
      }}
      const picked = await vscode.window.showQuickPick(
        sessions.map((item) => ({{
          label: item.title || item.session_id,
          description: item.status || '',
          detail: item.session_id,
          session: item,
        }})),
        {{placeHolder: 'Choose an ADE session'}}
      );
      if (picked) await showJson('ADE session', picked.session);
    }} catch (error) {{
      vscode.window.showErrorMessage('ADE sessions: ' + error.message);
    }}
  }}));

  context.subscriptions.push(vscode.commands.registerCommand('ade.reviewCheckpoint', async () => {{
    try {{
      const sessionId = await vscode.window.showInputBox({{prompt: 'ADE session ID'}});
      if (!sessionId) return;
      const payload = await request('/api/v1/sessions/' + encodeURIComponent(sessionId) + '/checkpoint-review');
      await showJson('ADE checkpoint review', payload);
    }} catch (error) {{
      vscode.window.showErrorMessage('ADE checkpoint review: ' + error.message);
    }}
  }}));

  context.subscriptions.push(vscode.commands.registerCommand('ade.showCurrentContext', async () => {{
    try {{
      const {{editor, path}} = activeLocation();
      const line = editor.selection.active.line + 1;
      const payload = await request('/api/v1/ide/context', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: readPayload({{path, line, radius: 30}}),
      }});
      await showJson('ADE file context', payload);
    }} catch (error) {{
      vscode.window.showErrorMessage('ADE context: ' + error.message);
    }}
  }}));

  context.subscriptions.push(vscode.commands.registerCommand('ade.planSelectedEdit', async () => {{
    try {{
      const {{editor, path}} = activeLocation();
      const replacement = await vscode.window.showInputBox({{
        prompt: 'Replacement text (planning only; no file mutation is applied)',
      }});
      if (replacement === undefined) return;
      const startLine = editor.selection.start.line + 1;
      const endLine = Math.max(startLine, editor.selection.end.line + 1);
      const payload = await request('/api/v1/ide/edit-plan', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: readPayload({{
          path,
          replacements: [{{start_line: startLine, end_line: endLine, text: replacement}}],
        }}, 'builder'),
      }});
      await showJson('ADE selected-edit plan', payload);
      vscode.window.showInformationMessage(
        'ADE generated a hash-bound edit plan. Apply/approval remains in the governed ADE workflow.'
      );
    }} catch (error) {{
      vscode.window.showErrorMessage('ADE edit plan: ' + error.message);
    }}
  }}));

  context.subscriptions.push(vscode.commands.registerCommand('ade.startHostedRunner', () => {{
    const term = vscode.window.createTerminal({{name: 'ADE Hosted Runner'}});
    term.sendText('python scripts/run_hosted_runner.py --project . --json');
    term.show();
  }}));

  context.subscriptions.push(vscode.commands.registerCommand('ade.startAutomationWorker', () => {{
    const term = vscode.window.createTerminal({{name: 'ADE Automations'}});
    term.sendText('python scripts/run_automation_worker.py --project . --json');
    term.show();
  }}));
}}
function deactivate() {{}}
module.exports = {{ activate, deactivate }};
"""
        files = {
            ".ade/ide.json": json.dumps(
                {
                    "version": 2,
                    "console_url": console,
                    "api_url": api,
                    "protocol": "ade-desktop-bridge/2",
                    "runner_database": ".ade/hosted-runner.db",
                    "automation_database": ".ade/automations.db",
                    "semantic_database": ".ade/semantic.db",
                    "session_database": ".ade/sessions.db",
                    "policy": {
                        "edit_planning": "read_only",
                        "mutations": "ToolRegistry approval flow only",
                    },
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
                "This project-scoped extension exposes ADE session browsing, checkpoint review, "
                "current-file context, hash-bound selected-edit planning, the operator console, "
                "and worker controls. The extension does not apply file/data mutations directly; "
                "approval and execution remain inside the ADE ToolRegistry policy boundary.\n"
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
            "api_url": api,
            "extension_directory": extension_root.as_posix(),
            "capabilities": [
                "sessions",
                "checkpoint_review",
                "file_context",
                "selected_edit_plan",
                "hosted_runner",
                "automations",
            ],
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
