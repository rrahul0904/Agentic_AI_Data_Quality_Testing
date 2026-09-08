"""Governed dbt command runtime with structured artifact evidence."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class DbtExecution:
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    artifacts: dict[str, Any]
    selected_nodes: tuple[str, ...]
    failed_nodes: tuple[dict[str, Any], ...]
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "shell_preview": " ".join(shlex.quote(item) for item in self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "stdout_summary": self.stdout[-8000:],
            "stderr_summary": self.stderr[-8000:],
            "artifacts": self.artifacts,
            "selected_nodes": list(self.selected_nodes),
            "failed_nodes": list(self.failed_nodes),
            "status": self.status,
        }


Runner = Callable[[Sequence[str], Path, dict[str, str], int], subprocess.CompletedProcess[str]]


def _default_runner(
    argv: Sequence[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class DbtRuntime:
    ALLOWED = {"parse", "ls", "compile", "run", "test", "build", "seed", "snapshot"}

    def __init__(
        self,
        project_dir: str | Path,
        *,
        profiles_dir: str | Path | None = None,
        executable: str = "dbt",
        runner: Runner | None = None,
        timeout: int = 1800,
    ) -> None:
        self.project_dir = Path(project_dir).expanduser().resolve()
        self.profiles_dir = Path(profiles_dir).expanduser().resolve() if profiles_dir else None
        self.executable = executable
        self.runner = runner or _default_runner
        self.timeout = timeout
        if not (self.project_dir / "dbt_project.yml").is_file():
            raise FileNotFoundError(f"dbt project not found: {self.project_dir / 'dbt_project.yml'}")

    def command(
        self,
        verb: str,
        *,
        select: str | Sequence[str] | None = None,
        exclude: str | Sequence[str] | None = None,
        target: str | None = None,
        vars: dict[str, Any] | None = None,
        state: str | Path | None = None,
        defer: bool = False,
        output: str | None = None,
        extra: Sequence[str] = (),
    ) -> tuple[str, ...]:
        if verb not in self.ALLOWED:
            raise ValueError(f"unsupported dbt verb: {verb}")
        argv = [self.executable, verb, "--project-dir", str(self.project_dir)]
        if self.profiles_dir:
            argv += ["--profiles-dir", str(self.profiles_dir)]
        if select:
            values = [select] if isinstance(select, str) else list(select)
            argv += ["--select", " ".join(str(item) for item in values)]
        if exclude:
            values = [exclude] if isinstance(exclude, str) else list(exclude)
            argv += ["--exclude", " ".join(str(item) for item in values)]
        if target:
            argv += ["--target", target]
        if vars:
            argv += ["--vars", json.dumps(vars, sort_keys=True, separators=(",", ":"))]
        if state:
            argv += ["--state", str(Path(state).expanduser().resolve())]
        if defer:
            if not state:
                raise ValueError("--defer requires --state")
            argv.append("--defer")
        if output and verb == "ls":
            argv += ["--output", output]
        argv += list(extra)
        return tuple(argv)

    def execute(self, verb: str, **kwargs: Any) -> dict[str, Any]:
        timeout = int(kwargs.pop("timeout", self.timeout))
        env_overrides = dict(kwargs.pop("env", {}) or {})
        argv = self.command(verb, **kwargs)
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in env_overrides.items()})
        started = time.perf_counter()
        try:
            completed = self.runner(argv, self.project_dir, env, timeout)
            duration = time.perf_counter() - started
        except subprocess.TimeoutExpired as exc:
            return {
                "command": list(argv),
                "exit_code": None,
                "duration_seconds": time.perf_counter() - started,
                "stdout_summary": str(exc.stdout or "")[-8000:],
                "stderr_summary": str(exc.stderr or "")[-8000:],
                "artifacts": self._artifacts(),
                "selected_nodes": [],
                "failed_nodes": [],
                "status": "FAIL",
                "error": f"dbt {verb} timed out after {timeout}s",
            }
        except FileNotFoundError:
            return {
                "command": list(argv),
                "exit_code": None,
                "duration_seconds": time.perf_counter() - started,
                "stdout_summary": "",
                "stderr_summary": "",
                "artifacts": self._artifacts(),
                "selected_nodes": [],
                "failed_nodes": [],
                "status": "SKIP_EXTERNAL",
                "error": f"dbt executable not found: {self.executable}",
            }

        artifacts = self._artifacts()
        run_results = artifacts.get("run_results") or {}
        results = run_results.get("results", ())
        selected = tuple(
            str(item.get("unique_id"))
            for item in results
            if item.get("unique_id")
        )
        failed = tuple(
            {
                "unique_id": item.get("unique_id"),
                "status": item.get("status"),
                "message": item.get("message"),
                "failures": item.get("failures"),
            }
            for item in results
            if str(item.get("status", "")).casefold()
            not in {"success", "pass", "skipped", "warn"}
        )
        artifact_failure = bool(failed)
        status = "PASS" if completed.returncode == 0 and not artifact_failure else "FAIL"
        execution = DbtExecution(
            command=argv,
            exit_code=int(completed.returncode),
            duration_seconds=duration,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            artifacts=artifacts,
            selected_nodes=selected,
            failed_nodes=failed,
            status=status,
        )
        result = execution.as_dict()
        result["verb"] = verb
        result["artifact_status_overrode_exit_code"] = completed.returncode == 0 and artifact_failure
        return result

    def _read_json(self, name: str) -> dict[str, Any] | None:
        path = self.project_dir / "target" / name
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _artifacts(self) -> dict[str, Any]:
        return {
            "manifest": self._read_json("manifest.json"),
            "run_results": self._read_json("run_results.json"),
            "catalog": self._read_json("catalog.json"),
            "sources": self._read_json("sources.json"),
        }
