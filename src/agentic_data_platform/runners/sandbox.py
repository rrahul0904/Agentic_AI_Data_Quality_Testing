"""Strong container-backed shell sandbox for CoCo-parity execution.

LOCAL_CONSTRAINED execution lives in advanced_capabilities.py.  This module is
only for execution that can truthfully be described as a container sandbox.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Any, Iterable


EXECUTION_CLASS = "CONTAINER_SANDBOX"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cwd(workspace: str | Path, cwd: str | Path) -> tuple[Path, str]:
    root = _root(workspace)
    target = (root / Path(cwd)).resolve(strict=False)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("cwd escapes the governed workspace") from exc
    target.mkdir(parents=True, exist_ok=True)
    container_cwd = "/workspace" if str(relative) == "." else f"/workspace/{relative.as_posix()}"
    return target, container_cwd


def _argv(command: str | Iterable[str]) -> list[str]:
    argv = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if not argv:
        raise ValueError("command is required")
    return argv


def _docker_binary(docker_executable: str) -> str | None:
    candidate = Path(docker_executable).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    return shutil.which(docker_executable)


def sandbox_shell_plan(
    workspace: str | Path,
    command: str | Iterable[str],
    *,
    cwd: str = ".",
    image: str = "python:3.12-slim",
    network_enabled: bool = False,
    workspace_write: bool = True,
    timeout_seconds: int = 120,
    max_output_bytes: int = 131072,
    memory_mb: int = 512,
    cpus: float = 1.0,
    pids_limit: int = 256,
    background: bool = False,
    docker_executable: str = "docker",
) -> dict[str, Any]:
    root = _root(workspace)
    _, container_cwd = _cwd(root, cwd)
    argv = _argv(command)
    timeout = max(1, min(int(timeout_seconds), 3600))
    output_cap = max(1024, min(int(max_output_bytes), 2_000_000))
    memory = max(64, min(int(memory_mb), 32768))
    cpu_limit = max(0.1, min(float(cpus), 64.0))
    pid_cap = max(16, min(int(pids_limit), 4096))
    if not image.strip():
        raise ValueError("image is required")

    job_seed = {
        "workspace": str(root),
        "cwd": container_cwd,
        "image": image,
        "argv": argv,
        "background": bool(background),
    }
    container_name = f"ade-sandbox-{_digest(job_seed)[:16]}" if background else None
    mount_mode = "rw" if workspace_write else "ro"

    docker_args = [
        docker_executable,
        "run",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(pid_cap),
        "--memory",
        f"{memory}m",
        "--cpus",
        str(cpu_limit),
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--network",
        "bridge" if network_enabled else "none",
        "-v",
        f"{root}:/workspace:{mount_mode}",
        "-w",
        container_cwd,
    ]
    if background:
        docker_args.extend(["-d", "--name", str(container_name)])
    else:
        docker_args.append("--rm")
    docker_args.extend([image, *argv])

    payload = {
        "execution_class": EXECUTION_CLASS,
        "sandboxed": True,
        "docker_executable": docker_executable,
        "image": image,
        "argv": argv,
        "cwd": str(Path(cwd)),
        "container_cwd": container_cwd,
        "network_enabled": bool(network_enabled),
        "workspace_write": bool(workspace_write),
        "timeout_seconds": timeout,
        "max_output_bytes": output_cap,
        "memory_mb": memory,
        "cpus": cpu_limit,
        "pids_limit": pid_cap,
        "background": bool(background),
        "container_name": container_name,
        "docker_command": docker_args,
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "approval_fingerprint": _digest(payload),
        "security": {
            "implicit_shell": False,
            "root_filesystem_read_only": True,
            "capabilities_dropped": "ALL",
            "no_new_privileges": True,
            "network_default": "DENY",
            "resource_limits": True,
            "workspace_mount": mount_mode,
        },
    }


def _record_path(workspace: str | Path, job_id: str) -> Path:
    return _root(workspace) / ".ade" / "sandbox" / f"{job_id}.json"


def _write_record(workspace: str | Path, record: dict[str, Any]) -> None:
    path = _record_path(workspace, str(record["job_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def _read_record(workspace: str | Path, job_id: str) -> dict[str, Any]:
    path = _record_path(workspace, job_id)
    if not path.exists():
        raise KeyError(f"sandbox job not found: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def sandbox_shell_run(
    workspace: str | Path,
    command: str | Iterable[str],
    *,
    approval_fingerprint: str,
    cwd: str = ".",
    image: str = "python:3.12-slim",
    network_enabled: bool = False,
    workspace_write: bool = True,
    timeout_seconds: int = 120,
    max_output_bytes: int = 131072,
    memory_mb: int = 512,
    cpus: float = 1.0,
    pids_limit: int = 256,
    background: bool = False,
    docker_executable: str = "docker",
) -> dict[str, Any]:
    plan = sandbox_shell_plan(
        workspace,
        command,
        cwd=cwd,
        image=image,
        network_enabled=network_enabled,
        workspace_write=workspace_write,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        memory_mb=memory_mb,
        cpus=cpus,
        pids_limit=pids_limit,
        background=background,
        docker_executable=docker_executable,
    )
    if approval_fingerprint != plan["approval_fingerprint"]:
        return {
            "status": "STALE_APPROVAL",
            "approval_fingerprint": plan["approval_fingerprint"],
            "execution_class": EXECUTION_CLASS,
        }
    binary = _docker_binary(docker_executable)
    if binary is None:
        return {
            "status": "BLOCKED_UNAVAILABLE",
            "execution_class": EXECUTION_CLASS,
            "sandboxed": False,
            "reason": "Docker executable is unavailable; refusing to downgrade to an unsandboxed process.",
            "approval_fingerprint": plan["approval_fingerprint"],
        }

    command_line = list(plan["docker_command"])
    command_line[0] = binary
    try:
        completed = subprocess.run(
            command_line,
            cwd=_root(workspace),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=int(plan["timeout_seconds"]) + 15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "TIMEOUT",
            "execution_class": EXECUTION_CLASS,
            "sandboxed": True,
            "stdout": str(exc.stdout or "")[: int(plan["max_output_bytes"])],
            "stderr": str(exc.stderr or "")[: int(plan["max_output_bytes"])],
            "approval_fingerprint": plan["approval_fingerprint"],
        }

    stdout = (completed.stdout or "")[: int(plan["max_output_bytes"])]
    stderr = (completed.stderr or "")[: int(plan["max_output_bytes"])]
    if background:
        if completed.returncode != 0:
            return {
                "status": "FAIL",
                "execution_class": EXECUTION_CLASS,
                "sandboxed": True,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "approval_fingerprint": plan["approval_fingerprint"],
            }
        container_id = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        job_id = f"sandbox_{_digest({'container_id': container_id, 'fingerprint': plan['approval_fingerprint']})[:16]}"
        record = {
            "job_id": job_id,
            "container_id": container_id,
            "container_name": plan["container_name"],
            "status": "RUNNING",
            "started_at": _utc_now(),
            "approval_fingerprint": plan["approval_fingerprint"],
            "execution_class": EXECUTION_CLASS,
            "sandboxed": True,
            "docker_executable": docker_executable,
            "max_output_bytes": plan["max_output_bytes"],
        }
        _write_record(workspace, record)
        return record

    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "execution_class": EXECUTION_CLASS,
        "sandboxed": True,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "approval_fingerprint": plan["approval_fingerprint"],
    }


def sandbox_shell_status(
    workspace: str | Path,
    job_id: str,
    *,
    docker_executable: str | None = None,
) -> dict[str, Any]:
    record = _read_record(workspace, job_id)
    binary = _docker_binary(docker_executable or record["docker_executable"])
    if binary is None:
        return {**record, "status": "BLOCKED_UNAVAILABLE", "reason": "Docker executable is unavailable."}
    name = record.get("container_name") or record.get("container_id")
    completed = subprocess.run(
        [binary, "inspect", "-f", "{{.State.Status}}|{{.State.ExitCode}}", str(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {**record, "status": "UNKNOWN", "stderr": (completed.stderr or "")[:4096]}
    state, _, exit_code = (completed.stdout or "").strip().partition("|")
    normalized = {
        "running": "RUNNING",
        "created": "RUNNING",
        "restarting": "RUNNING",
        "exited": "EXITED",
        "dead": "EXITED",
    }.get(state.casefold(), state.upper() or "UNKNOWN")
    return {**record, "status": normalized, "container_state": state, "exit_code": int(exit_code or 0)}


def sandbox_shell_logs(
    workspace: str | Path,
    job_id: str,
    *,
    docker_executable: str | None = None,
) -> dict[str, Any]:
    record = _read_record(workspace, job_id)
    binary = _docker_binary(docker_executable or record["docker_executable"])
    if binary is None:
        return {**record, "status": "BLOCKED_UNAVAILABLE", "reason": "Docker executable is unavailable."}
    name = record.get("container_name") or record.get("container_id")
    completed = subprocess.run(
        [binary, "logs", str(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    cap = int(record.get("max_output_bytes", 131072))
    return {
        **record,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "stdout": (completed.stdout or "")[:cap],
        "stderr": (completed.stderr or "")[:cap],
    }


def sandbox_shell_kill(
    workspace: str | Path,
    job_id: str,
    *,
    docker_executable: str | None = None,
) -> dict[str, Any]:
    record = _read_record(workspace, job_id)
    binary = _docker_binary(docker_executable or record["docker_executable"])
    if binary is None:
        return {**record, "status": "BLOCKED_UNAVAILABLE", "reason": "Docker executable is unavailable."}
    name = record.get("container_name") or record.get("container_id")
    stop = subprocess.run(
        [binary, "stop", "--time", "5", str(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        [binary, "rm", "-f", str(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    updated = {
        **record,
        "status": "TERMINATED" if stop.returncode == 0 else "FAIL",
        "ended_at": _utc_now(),
        "stderr": (stop.stderr or "")[:4096],
    }
    _write_record(workspace, updated)
    return updated
