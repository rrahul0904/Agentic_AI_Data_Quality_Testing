"""Reproducible, truthfulness-first adapter for dbt Labs ADE-bench.

ADE-bench installs its own executable named ``ade``. This adapter therefore requires an
explicit benchmark repository and resolves the benchmark executable from that repository
(or an explicit path) instead of invoking the Agentic Data Engineering OS ``ade`` command.

Current upstream ADE-bench does not expose this product as a native ``--agent ade`` driver.
Requests for that agent are reported as BLOCKED_EXTERNAL rather than assigned a synthetic
score. Successful external harness execution is evidence that the harness ran, not by
itself a parsed benchmark score.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Sequence


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_UPSTREAM_NATIVE_AGENTS = frozenset({"sage", "claude", "codex", "gemini"})


@dataclass(frozen=True)
class ADEBenchSpec:
    repository: str | Path
    tasks: tuple[str, ...] = ("all",)
    database: str = "duckdb"
    project_type: str = "dbt"
    agent: str = "ade"
    model: str | None = None
    executable: str | Path | None = None
    plugin_sets: tuple[str, ...] = ()
    attempts: int = 1
    concurrency: int = 1
    max_episodes: int = 50
    no_diffs: bool = False
    persist: bool = False
    tasks_dir: str | Path | None = None
    credential_env: tuple[str, ...] = ()
    timeout_seconds: int = 14_400

    def validate(self) -> None:
        if not self.tasks or any(not str(task).strip() for task in self.tasks):
            raise ValueError("at least one non-empty ADE-Bench task selector is required")
        if self.database not in {"duckdb", "snowflake"}:
            raise ValueError("database must be duckdb or snowflake")
        if self.project_type not in {"dbt", "dbt-fusion"}:
            raise ValueError("project_type must be dbt or dbt-fusion")
        if self.attempts < 1 or self.attempts > 100:
            raise ValueError("attempts must be between 1 and 100")
        if self.concurrency < 1 or self.concurrency > 64:
            raise ValueError("concurrency must be between 1 and 64")
        if self.max_episodes < 1 or self.max_episodes > 1000:
            raise ValueError("max_episodes must be between 1 and 1000")
        if self.timeout_seconds < 1 or self.timeout_seconds > 172_800:
            raise ValueError("timeout_seconds must be between 1 and 172800")


@dataclass(frozen=True)
class ADEBenchEvidence:
    status: str
    benchmark: str
    upstream_repository: str
    upstream_commit: str | None
    agent: str
    model: str | None
    command: tuple[str, ...]
    working_directory: str
    executed: bool
    returncode: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    benchmark_score: float | None = None
    blocked_reasons: tuple[str, ...] = ()
    truthfulness: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ADEBenchRunner:
    """Plan and optionally execute a pinned external ADE-Bench harness run."""

    benchmark_name = "dbt-labs/ade-bench"

    def __init__(
        self,
        spec: ADEBenchSpec,
        *,
        runner: CommandRunner | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        spec.validate()
        self.spec = spec
        self.runner = runner or subprocess.run
        self.environ = dict(os.environ if environ is None else environ)
        self.repository = Path(spec.repository).expanduser().resolve()
        if spec.executable is None:
            executable_name = "ade.exe" if os.name == "nt" else "ade"
            self.executable = self.repository / ".venv" / ("Scripts" if os.name == "nt" else "bin") / executable_name
        else:
            self.executable = Path(spec.executable).expanduser().resolve()

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _tail(value: str, limit: int = 4000) -> str:
        return value[-limit:] if len(value) > limit else value

    def _git_commit(self) -> str | None:
        if not self.repository.is_dir():
            return None
        try:
            completed = self.runner(
                ["git", "-C", str(self.repository), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        value = str(completed.stdout or "").strip()
        return value if len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value) else None

    def _command(self) -> tuple[str, ...]:
        command = [str(self.executable), "run", *[str(task) for task in self.spec.tasks]]
        command += ["--db", self.spec.database, "--project-type", self.spec.project_type, "--agent", self.spec.agent]
        if self.spec.model:
            command += ["--model", self.spec.model]
        command += ["--n-concurrent-trials", str(self.spec.concurrency)]
        command += ["--n-attempts", str(self.spec.attempts)]
        command += ["--max-episodes", str(self.spec.max_episodes)]
        for plugin_set in self.spec.plugin_sets:
            if str(plugin_set).strip():
                command += ["--plugin-set", str(plugin_set).strip()]
        if self.spec.tasks_dir is not None:
            command += ["--tasks-dir", str(Path(self.spec.tasks_dir).expanduser().resolve())]
        if self.spec.no_diffs:
            command.append("--no-diffs")
        if self.spec.persist:
            command.append("--persist")
        return tuple(command)

    def _blocked_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.repository.is_dir():
            reasons.append(f"ADE-Bench repository not found: {self.repository}")
        if not self.executable.is_file():
            reasons.append(f"ADE-Bench executable not found: {self.executable}")
        if self.spec.agent.casefold() not in _UPSTREAM_NATIVE_AGENTS:
            reasons.append(
                "current upstream ADE-Bench has no native driver for agent "
                f"{self.spec.agent!r}; supported adapter targets are {', '.join(sorted(_UPSTREAM_NATIVE_AGENTS))}"
            )
        missing_credentials = [name for name in self.spec.credential_env if not self.environ.get(name)]
        if missing_credentials:
            reasons.append("required external credential environment is missing: " + ", ".join(missing_credentials))
        if self.spec.database == "snowflake" and not self.spec.credential_env:
            reasons.append(
                "Snowflake benchmark execution requires explicit credential_env names; "
                "the adapter will not infer or embed warehouse credentials"
            )
        return tuple(reasons)

    def plan(self) -> ADEBenchEvidence:
        reasons = self._blocked_reasons()
        commit = self._git_commit()
        return ADEBenchEvidence(
            status="BLOCKED_EXTERNAL" if reasons else "NOT_RUN_EXTERNAL",
            benchmark=self.benchmark_name,
            upstream_repository=str(self.repository),
            upstream_commit=commit,
            agent=self.spec.agent,
            model=self.spec.model,
            command=self._command(),
            working_directory=str(self.repository),
            executed=False,
            blocked_reasons=reasons,
            truthfulness={
                "upstream_native_agent": self.spec.agent.casefold() in _UPSTREAM_NATIVE_AGENTS,
                "score_parsed": False,
                "score_claimed": False,
                "successful_process_is_not_a_benchmark_score": True,
                "cli_collision_avoided_by_explicit_executable": True,
            },
        )

    def execute(self, *, execute: bool = False) -> ADEBenchEvidence:
        plan = self.plan()
        if plan.status == "BLOCKED_EXTERNAL" or not execute:
            return plan

        started = datetime.now(timezone.utc).isoformat()
        try:
            completed = self.runner(
                list(plan.command),
                cwd=str(self.repository),
                capture_output=True,
                text=True,
                timeout=self.spec.timeout_seconds,
                check=False,
                env=self.environ,
            )
            stdout = str(completed.stdout or "")
            stderr = str(completed.stderr or "")
            returncode = int(completed.returncode)
            status = "PASS_EXTERNAL_RUN" if returncode == 0 else "FAIL_EXTERNAL_RUN"
        except (OSError, subprocess.SubprocessError) as exc:
            stdout = ""
            stderr = str(exc)
            returncode = -1
            status = "FAIL_EXTERNAL_RUN"
        finished = datetime.now(timezone.utc).isoformat()
        return ADEBenchEvidence(
            status=status,
            benchmark=self.benchmark_name,
            upstream_repository=str(self.repository),
            upstream_commit=plan.upstream_commit,
            agent=self.spec.agent,
            model=self.spec.model,
            command=plan.command,
            working_directory=str(self.repository),
            executed=True,
            returncode=returncode,
            started_at=started,
            finished_at=finished,
            stdout_sha256=self._sha256(stdout),
            stderr_sha256=self._sha256(stderr),
            stdout_tail=self._tail(stdout),
            stderr_tail=self._tail(stderr),
            benchmark_score=None,
            blocked_reasons=(),
            truthfulness={
                **dict(plan.truthfulness or {}),
                "process_exit_success": returncode == 0,
                "score_parsed": False,
                "score_claimed": False,
            },
        )

    def write_evidence(self, path: str | Path, *, execute: bool = False) -> ADEBenchEvidence:
        evidence = self.execute(execute=execute)
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(evidence.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return evidence