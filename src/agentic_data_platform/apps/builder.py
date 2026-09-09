"""Snowflake Streamlit and App Runtime project builder."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import yaml


def _safe_name(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value)).strip("_")
    if not text or not text[0].isalpha():
        raise ValueError("app name must start with a letter and contain letters, digits, or underscores")
    return text


def _fingerprint(files: dict[str, str]) -> str:
    material = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


class SnowflakeAppBuilder:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    def plan(
        self,
        *,
        kind: str,
        app_name: str,
        directory: str,
        database: str,
        schema: str,
        query_warehouse: str,
        title: str | None = None,
        compute_pool: str | None = None,
        streamlit_runtime: str = "container",
    ) -> dict[str, Any]:
        kind = str(kind).casefold()
        name = _safe_name(app_name)
        relative = Path(directory)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("app directory must be project-relative")
        target = (self.project_root / relative).resolve()
        if self.project_root not in target.parents and target != self.project_root:
            raise ValueError("app directory escapes project root")

        if kind == "streamlit":
            runtime = str(streamlit_runtime).casefold()
            if runtime not in {"container", "warehouse"}:
                raise ValueError("streamlit_runtime must be container or warehouse")
            entity: dict[str, Any] = {
                "type": "streamlit",
                "identifier": name,
                "query_warehouse": query_warehouse,
                "main_file": "streamlit_app.py",
                "artifacts": ["streamlit_app.py", "environment.yml"],
            }
            if title:
                entity["title"] = title
            if runtime == "container":
                if not compute_pool:
                    raise ValueError("container Streamlit plans require compute_pool")
                entity["compute_pool"] = compute_pool
                entity["runtime_name"] = "SYSTEM$ST_CONTAINER_RUNTIME_PY3_11"
            files = {
                "snowflake.yml": yaml.safe_dump(
                    {
                        "definition_version": 2,
                        "entities": {name: entity},
                    },
                    sort_keys=False,
                ),
                "environment.yml": "name: ade-streamlit\ndependencies:\n  - python=3.11\n  - streamlit\n  - snowflake-snowpark-python\n",
                "streamlit_app.py": (
                    "import streamlit as st\n"
                    "from snowflake.snowpark.context import get_active_session\n\n"
                    "st.set_page_config(layout='wide')\n"
                    f"st.title({(title or name.replace('_', ' ').title())!r})\n"
                    "session = get_active_session()\n"
                    "st.caption('Deployed by Agentic Data Engineering OS')\n"
                    "health = session.sql('SELECT CURRENT_USER() AS USER, CURRENT_ROLE() AS ROLE').collect()[0]\n"
                    "st.success(f\"Connected as {health['USER']} with role {health['ROLE']}\")\n"
                ),
            }
            deploy = ["snow", "streamlit", "deploy", name, "--replace"]
        elif kind in {"app-runtime", "app_runtime", "app"}:
            files = {
                "app.yml": yaml.safe_dump(
                    {
                        "version": 2,
                        "name": name,
                        "database": database,
                        "schema": schema,
                        "query_warehouse": query_warehouse,
                        "label": title or name.replace("_", " ").title(),
                        "description": "Generated and governed by Agentic Data Engineering OS.",
                        "ignore": ["node_modules", ".git", ".env*"],
                        "run": {"command": ["node", "server.js"]},
                    },
                    sort_keys=False,
                ),
                "package.json": json.dumps(
                    {
                        "name": name.casefold().replace("_", "-"),
                        "version": "1.0.0",
                        "private": True,
                        "scripts": {"start": "node server.js"},
                    },
                    indent=2,
                ) + "\n",
                "server.js": (
                    "const http = require('http');\n"
                    "const port = Number(process.env.PORT || 3000);\n"
                    "const server = http.createServer((req, res) => {\n"
                    "  if (req.url === '/healthz') {\n"
                    "    res.writeHead(200, {'content-type': 'application/json'});\n"
                    "    return res.end(JSON.stringify({status: 'ok', service: 'ade-app-runtime'}));\n"
                    "  }\n"
                    "  res.writeHead(200, {'content-type': 'text/html; charset=utf-8'});\n"
                    f"  res.end('<!doctype html><html><body><h1>{title or name}</h1><p>Agentic Data Engineering OS application.</p></body></html>');\n"
                    "});\n"
                    "server.listen(port, '0.0.0.0', () => console.log('listening on ' + port));\n"
                ),
            }
            deploy = ["snow", "app", "deploy"]
        else:
            raise ValueError("kind must be streamlit or app-runtime")

        return {
            "status": "PASS",
            "kind": "streamlit" if kind == "streamlit" else "app-runtime",
            "app_name": name,
            "directory": relative.as_posix(),
            "target": str(target),
            "files": files,
            "approval_fingerprint": _fingerprint(files),
            "deploy_command": deploy,
        }

    def apply(self, plan: dict[str, Any], *, approval_fingerprint: str, overwrite: bool = False) -> dict[str, Any]:
        if approval_fingerprint != plan.get("approval_fingerprint"):
            return {"status": "BLOCKED_APPROVAL", "reason": "app plan does not match approved fingerprint"}
        target = Path(str(plan["target"])).resolve()
        if self.project_root not in target.parents and target != self.project_root:
            raise ValueError("app plan target escapes project root")
        if target.exists() and any(target.iterdir()) and not overwrite:
            raise FileExistsError(f"app directory is not empty: {target}")
        target.mkdir(parents=True, exist_ok=True)
        written = []
        for relative, content in dict(plan["files"]).items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content))
            written.append(str(path.relative_to(self.project_root)))
        verified = all((target / path).read_text() == content for path, content in plan["files"].items())
        return {
            "status": "PASS" if verified else "FAIL",
            "verified": verified,
            "directory": plan["directory"],
            "written": written,
            "approval_fingerprint": approval_fingerprint,
        }

    @staticmethod
    def deploy(
        plan: dict[str, Any],
        *,
        connection: str | None = None,
        target: str | None = None,
        open_app: bool = False,
        timeout_seconds: int = 1800,
    ) -> dict[str, Any]:
        command = list(plan["deploy_command"])
        if plan["kind"] == "streamlit" and open_app:
            command.append("--open")
        if plan["kind"] == "app-runtime" and target:
            command += ["--target", str(target)]
        if connection:
            command += ["--connection", str(connection)]
        if shutil.which("snow") is None:
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "Snowflake CLI executable 'snow' is not installed",
                "command": command,
            }
        process = subprocess.run(
            command,
            cwd=Path(str(plan["target"])),
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
        return {
            "status": "PASS" if process.returncode == 0 else "FAIL",
            "returncode": process.returncode,
            "stdout": process.stdout[-12000:],
            "stderr": process.stderr[-8000:],
            "command": command,
        }

    @staticmethod
    def validate(plan: dict[str, Any]) -> dict[str, Any]:
        files = dict(plan.get("files") or {})
        errors = []
        if plan.get("kind") == "streamlit":
            try:
                manifest = yaml.safe_load(files["snowflake.yml"])
                if manifest.get("definition_version") != 2:
                    errors.append("snowflake.yml definition_version must be 2")
                entities = manifest.get("entities") or {}
                if plan.get("app_name") not in entities:
                    errors.append("Streamlit entity missing from snowflake.yml")
            except Exception as exc:
                errors.append(f"snowflake.yml invalid: {exc}")
        else:
            try:
                manifest = yaml.safe_load(files["app.yml"])
                for field in ("version", "name", "database", "schema", "query_warehouse"):
                    if manifest.get(field) in {None, ""}:
                        errors.append(f"app.yml missing {field}")
                if manifest.get("version") != 2:
                    errors.append("app.yml version must be 2")
            except Exception as exc:
                errors.append(f"app.yml invalid: {exc}")
        return {"status": "FAIL" if errors else "PASS", "errors": errors}
