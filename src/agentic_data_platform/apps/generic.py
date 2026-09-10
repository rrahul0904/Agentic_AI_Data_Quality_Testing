"""Provider-neutral application scaffold, preview, deploy, verify and rollback workflow."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.request import urlopen


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("application directory must be workspace-relative")
    return path


def _safe_name(value: str) -> str:
    name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value)).strip("-_")
    if not name:
        raise ValueError("application name is required")
    return name[:80]


class GenericAppWorkflow:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    def scaffold_plan(
        self,
        *,
        app_name: str,
        directory: str,
        framework: str = "python-http",
        title: str | None = None,
        port: int = 8080,
    ) -> dict[str, Any]:
        name = _safe_name(app_name)
        relative = _safe_relative(directory)
        target = (self.project_root / relative).resolve()
        if target != self.project_root and self.project_root not in target.parents:
            raise ValueError("application directory escapes workspace")
        port = max(1024, min(int(port), 65535))
        framework_key = str(framework).casefold().replace("_", "-")
        display = title or name.replace("-", " ").replace("_", " ").title()

        if framework_key == "python-http":
            files = {
                "app.py": (
                    "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
                    "import json\nimport os\n\n"
                    "class Handler(BaseHTTPRequestHandler):\n"
                    "    def do_GET(self):\n"
                    "        if self.path == '/healthz':\n"
                    "            body = json.dumps({'status': 'ok'}).encode()\n"
                    "            self.send_response(200); self.send_header('content-type', 'application/json')\n"
                    "            self.end_headers(); self.wfile.write(body); return\n"
                    "        body = " + repr(f"<!doctype html><html><body><h1>{display}</h1><p>Agentic Data Engineering OS application.</p></body></html>") + ".encode()\n"
                    "        self.send_response(200); self.send_header('content-type', 'text/html; charset=utf-8')\n"
                    "        self.end_headers(); self.wfile.write(body)\n\n"
                    f"HTTPServer(('0.0.0.0', int(os.getenv('PORT', '{port}'))), Handler).serve_forever()\n"
                ),
                "requirements.txt": "",
                "Dockerfile": (
                    "FROM python:3.12-slim\nWORKDIR /app\n"
                    "COPY . /app\nUSER 65532:65532\n"
                    f"ENV PORT={port}\nEXPOSE {port}\nCMD [\"python\", \"app.py\"]\n"
                ),
            }
            run_command = ["python", "app.py"]
            image = "python:3.12-slim"
        elif framework_key == "node-http":
            files = {
                "server.js": (
                    "const http = require('http');\n"
                    f"const port = Number(process.env.PORT || {port});\n"
                    "http.createServer((req, res) => {\n"
                    "  if (req.url === '/healthz') { res.writeHead(200, {'content-type':'application/json'}); return res.end(JSON.stringify({status:'ok'})); }\n"
                    f"  res.writeHead(200, {{'content-type':'text/html; charset=utf-8'}}); res.end({json.dumps(f'<!doctype html><html><body><h1>{display}</h1><p>Agentic Data Engineering OS application.</p></body></html>')});\n"
                    "}).listen(port, '0.0.0.0');\n"
                ),
                "package.json": json.dumps(
                    {"name": name.casefold(), "private": True, "version": "1.0.0", "scripts": {"start": "node server.js"}},
                    indent=2,
                ) + "\n",
                "Dockerfile": (
                    "FROM node:22-alpine\nWORKDIR /app\nCOPY . /app\nUSER node\n"
                    f"ENV PORT={port}\nEXPOSE {port}\nCMD [\"node\", \"server.js\"]\n"
                ),
            }
            run_command = ["node", "server.js"]
            image = "node:22-alpine"
        elif framework_key == "static":
            files = {
                "index.html": f"<!doctype html><html><body><h1>{display}</h1><p>Agentic Data Engineering OS application.</p></body></html>\n",
                "healthz": "ok\n",
                "Dockerfile": (
                    "FROM nginx:1.27-alpine\nCOPY . /usr/share/nginx/html\n"
                    f"EXPOSE {port}\n"
                ),
            }
            run_command = ["nginx", "-g", "daemon off;"]
            image = "nginx:1.27-alpine"
        else:
            raise ValueError("framework must be python-http, node-http, or static")

        payload = {
            "app_name": name,
            "framework": framework_key,
            "directory": relative.as_posix(),
            "target": str(target),
            "port": port,
            "health_path": "/healthz" if framework_key != "static" else "/healthz",
            "files": files,
            "run_command": run_command,
            "preview_image": image,
        }
        return {
            "status": "PASS",
            "mode": "PLAN_ONLY",
            **payload,
            "approval_fingerprint": _digest(payload),
        }

    def scaffold_apply(
        self,
        plan: dict[str, Any],
        *,
        approval_fingerprint: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        payload = {key: plan[key] for key in (
            "app_name", "framework", "directory", "target", "port",
            "health_path", "files", "run_command", "preview_image",
        )}
        expected = _digest(payload)
        if approval_fingerprint != expected or plan.get("approval_fingerprint") != expected:
            return {"status": "STALE_APPROVAL", "approval_fingerprint": expected}
        target = Path(str(plan["target"])).resolve()
        if target != self.project_root and self.project_root not in target.parents:
            raise ValueError("application target escapes workspace")
        if target.exists() and any(target.iterdir()) and not overwrite:
            raise FileExistsError(f"application directory is not empty: {target}")
        target.mkdir(parents=True, exist_ok=True)
        written = []
        for relative, body in dict(plan["files"]).items():
            destination = (target / _safe_relative(relative)).resolve()
            if destination != target and target not in destination.parents:
                raise ValueError("scaffold file escapes application directory")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(body), encoding="utf-8")
            written.append(destination.relative_to(self.project_root).as_posix())
        verified = all(
            (target / relative).read_text(encoding="utf-8") == body
            for relative, body in plan["files"].items()
        )
        return {
            "status": "PASS" if verified else "FAIL",
            "verified": verified,
            "written": written,
            "approval_fingerprint": expected,
        }

    def validate(self, plan: dict[str, Any]) -> dict[str, Any]:
        errors = []
        files = dict(plan.get("files") or {})
        for required in ("Dockerfile",):
            if required not in files:
                errors.append(f"missing {required}")
        if not plan.get("run_command"):
            errors.append("missing run command")
        if not str(plan.get("health_path") or "").startswith("/"):
            errors.append("health_path must be absolute")
        return {
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
            "scaffold_fingerprint": _digest(files),
        }

    def preview_plan(
        self,
        plan: dict[str, Any],
        *,
        host_port: int | None = None,
        memory_mb: int = 512,
        cpus: float = 1.0,
    ) -> dict[str, Any]:
        port = int(plan["port"])
        published = max(1024, min(int(host_port or port), 65535))
        image_name = f"ade-preview-{_safe_name(str(plan['app_name'])).casefold()}"
        container_name = image_name
        target = str(Path(plan["target"]).resolve())
        payload = {
            "app_name": plan["app_name"],
            "target": target,
            "image_name": image_name,
            "container_name": container_name,
            "container_port": port,
            "host_port": published,
            "memory_mb": max(64, min(int(memory_mb), 8192)),
            "cpus": max(0.1, min(float(cpus), 16.0)),
            "health_url": f"http://127.0.0.1:{published}{plan['health_path']}",
            "preview_url": f"http://127.0.0.1:{published}/",
        }
        return {
            "status": "PASS",
            "mode": "PLAN_ONLY",
            **payload,
            "approval_fingerprint": _digest(payload),
        }

    @staticmethod
    def preview_run(preview_plan: dict[str, Any], *, approval_fingerprint: str) -> dict[str, Any]:
        payload = {key: preview_plan[key] for key in (
            "app_name", "target", "image_name", "container_name", "container_port",
            "host_port", "memory_mb", "cpus", "health_url", "preview_url",
        )}
        expected = _digest(payload)
        if approval_fingerprint != expected or preview_plan.get("approval_fingerprint") != expected:
            return {"status": "STALE_APPROVAL", "approval_fingerprint": expected}
        docker = shutil.which("docker")
        if docker is None:
            return {
                "status": "BLOCKED_UNAVAILABLE",
                "reason": "Docker is required for isolated generic application preview.",
                "approval_fingerprint": expected,
            }
        build = subprocess.run(
            [docker, "build", "-t", str(preview_plan["image_name"]), "."],
            cwd=str(preview_plan["target"]),
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode != 0:
            return {"status": "FAIL", "phase": "build", "stderr": build.stderr[-8000:]}
        subprocess.run([docker, "rm", "-f", str(preview_plan["container_name"])], capture_output=True, text=True, check=False)
        command = [
            docker, "run", "-d", "--name", str(preview_plan["container_name"]),
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256", "--memory", f"{preview_plan['memory_mb']}m",
            "--cpus", str(preview_plan["cpus"]), "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-p", f"127.0.0.1:{preview_plan['host_port']}:{preview_plan['container_port']}",
            str(preview_plan["image_name"]),
        ]
        run = subprocess.run(command, capture_output=True, text=True, check=False)
        return {
            "status": "PASS" if run.returncode == 0 else "FAIL",
            "phase": "preview",
            "preview_url": preview_plan["preview_url"],
            "health_url": preview_plan["health_url"],
            "container_name": preview_plan["container_name"],
            "stdout": run.stdout[-4000:],
            "stderr": run.stderr[-8000:],
            "approval_fingerprint": expected,
        }

    @staticmethod
    def verify_url(url: str, *, timeout_seconds: int = 5) -> dict[str, Any]:
        try:
            with urlopen(str(url), timeout=max(1, min(int(timeout_seconds), 30))) as response:
                body = response.read(4096)
                status = int(response.status)
        except Exception as exc:
            return {"status": "FAIL", "url": url, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "status": "PASS" if 200 <= status < 300 else "FAIL",
            "url": url,
            "http_status": status,
            "body_sha256": sha256(body).hexdigest(),
        }

    def deployment_plan(
        self,
        plan: dict[str, Any],
        *,
        backend: str,
        image: str | None = None,
        namespace: str = "default",
        replicas: int = 1,
    ) -> dict[str, Any]:
        backend_key = str(backend).casefold().replace("_", "-")
        image_name = image or f"ade/{_safe_name(str(plan['app_name'])).casefold()}:latest"
        port = int(plan["port"])
        if backend_key == "docker":
            contract = {
                "backend": "docker",
                "image": image_name,
                "container_name": f"ade-{_safe_name(str(plan['app_name'])).casefold()}",
                "port": port,
                "target": str(Path(plan["target"]).resolve()),
            }
        elif backend_key in {"kubernetes", "k8s"}:
            name = _safe_name(str(plan["app_name"])).casefold().replace("_", "-")
            manifest = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name, "namespace": namespace},
                "spec": {
                    "replicas": max(1, min(int(replicas), 20)),
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name}},
                        "spec": {
                            "containers": [{
                                "name": name,
                                "image": image_name,
                                "ports": [{"containerPort": port}],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "runAsNonRoot": True,
                                },
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"},
                                    "limits": {"cpu": "1", "memory": "512Mi"},
                                },
                            }]
                        },
                    },
                },
            }
            contract = {
                "backend": "kubernetes",
                "image": image_name,
                "namespace": namespace,
                "name": name,
                "target": str(Path(plan["target"]).resolve()),
                "manifest": manifest,
            }
        else:
            raise ValueError("backend must be docker or kubernetes")
        return {
            "status": "PASS",
            "mode": "PLAN_ONLY",
            **contract,
            "approval_fingerprint": _digest(contract),
        }

    @staticmethod
    def deployment_run(deployment_plan: dict[str, Any], *, approval_fingerprint: str) -> dict[str, Any]:
        payload = {key: value for key, value in deployment_plan.items() if key not in {"status", "mode", "approval_fingerprint"}}
        expected = _digest(payload)
        if approval_fingerprint != expected or deployment_plan.get("approval_fingerprint") != expected:
            return {"status": "STALE_APPROVAL", "approval_fingerprint": expected}
        backend = deployment_plan["backend"]
        if backend == "docker":
            docker = shutil.which("docker")
            if docker is None:
                return {"status": "BLOCKED_UNAVAILABLE", "backend": backend, "reason": "Docker is unavailable."}
            build = subprocess.run(
                [docker, "build", "-t", deployment_plan["image"], "."],
                cwd=deployment_plan["target"],
                capture_output=True, text=True, check=False,
            )
            return {
                "status": "PASS" if build.returncode == 0 else "FAIL",
                "backend": backend,
                "phase": "image-build",
                "stdout": build.stdout[-4000:],
                "stderr": build.stderr[-8000:],
                "approval_fingerprint": expected,
            }
        kubectl = shutil.which("kubectl")
        if kubectl is None:
            return {"status": "BLOCKED_UNAVAILABLE", "backend": backend, "reason": "kubectl is unavailable."}
        process = subprocess.run(
            [kubectl, "apply", "-f", "-"],
            input=json.dumps(deployment_plan["manifest"]),
            capture_output=True, text=True, check=False,
        )
        return {
            "status": "PASS" if process.returncode == 0 else "FAIL",
            "backend": backend,
            "stdout": process.stdout[-4000:],
            "stderr": process.stderr[-8000:],
            "approval_fingerprint": expected,
        }

    @staticmethod
    def rollback_plan(deployment_plan: dict[str, Any]) -> dict[str, Any]:
        backend = str(deployment_plan["backend"])
        if backend == "docker":
            command = ["docker", "rm", "-f", str(deployment_plan["container_name"])]
        else:
            command = [
                "kubectl", "rollout", "undo",
                f"deployment/{deployment_plan['name']}",
                "-n", str(deployment_plan["namespace"]),
            ]
        payload = {"backend": backend, "command": command}
        return {
            "status": "PASS",
            "mode": "PLAN_ONLY",
            **payload,
            "approval_fingerprint": _digest(payload),
        }

    @staticmethod
    def rollback_run(rollback_plan: dict[str, Any], *, approval_fingerprint: str) -> dict[str, Any]:
        payload = {"backend": rollback_plan["backend"], "command": list(rollback_plan["command"])}
        expected = _digest(payload)
        if approval_fingerprint != expected or rollback_plan.get("approval_fingerprint") != expected:
            return {"status": "STALE_APPROVAL", "approval_fingerprint": expected}
        binary = shutil.which(str(rollback_plan["command"][0]))
        if binary is None:
            return {"status": "BLOCKED_UNAVAILABLE", "backend": rollback_plan["backend"]}
        command = [binary, *list(rollback_plan["command"])[1:]]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        return {
            "status": "PASS" if process.returncode == 0 else "FAIL",
            "backend": rollback_plan["backend"],
            "stdout": process.stdout[-4000:],
            "stderr": process.stderr[-8000:],
            "approval_fingerprint": expected,
        }
