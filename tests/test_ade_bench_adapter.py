from __future__ import annotations

import subprocess

from agentic_data_platform.benchmarks import ADEBenchRunner, ADEBenchSpec


UPSTREAM_SHA = "1234567890abcdef1234567890abcdef12345678"


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, stdout=UPSTREAM_SHA + "\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Harness run completed: 2 of 2 tasks successful\n",
            stderr="",
        )


def _repo(tmp_path):
    repo = tmp_path / "ade-bench"
    executable = repo / ".venv" / "bin" / "ade"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    return repo, executable


def test_ade_bench_blocks_fake_native_ade_score(tmp_path):
    repo, _ = _repo(tmp_path)
    runner = FakeRunner()
    adapter = ADEBenchRunner(
        ADEBenchSpec(repository=repo, tasks=("simple001",), agent="ade"),
        runner=runner,
        environ={},
    )
    evidence = adapter.execute(execute=True)
    assert evidence.status == "BLOCKED_EXTERNAL"
    assert evidence.executed is False
    assert evidence.benchmark_score is None
    assert evidence.truthfulness["score_claimed"] is False
    assert "no native driver" in " ".join(evidence.blocked_reasons)
    assert len(runner.calls) == 1  # git identity only; benchmark process never executes


def test_ade_bench_supported_external_run_records_reproducible_evidence_without_inventing_score(tmp_path):
    repo, executable = _repo(tmp_path)
    runner = FakeRunner()
    adapter = ADEBenchRunner(
        ADEBenchSpec(
            repository=repo,
            executable=executable,
            tasks=("simple001", "simple002"),
            database="duckdb",
            project_type="dbt",
            agent="codex",
            model="example-model",
            plugin_sets=("none",),
            credential_env=("OPENAI_API_KEY",),
            attempts=2,
            concurrency=1,
            no_diffs=True,
        ),
        runner=runner,
        environ={"OPENAI_API_KEY": "test-secret-never-recorded"},
    )

    planned = adapter.execute(execute=False)
    assert planned.status == "NOT_RUN_EXTERNAL"
    assert planned.executed is False
    assert planned.upstream_commit == UPSTREAM_SHA
    assert planned.command[0] == str(executable.resolve())
    assert planned.command[1:4] == ("run", "simple001", "simple002")
    assert "test-secret-never-recorded" not in " ".join(planned.command)

    evidence = adapter.execute(execute=True)
    assert evidence.status == "PASS_EXTERNAL_RUN"
    assert evidence.executed is True
    assert evidence.returncode == 0
    assert evidence.upstream_commit == UPSTREAM_SHA
    assert evidence.stdout_sha256 and len(evidence.stdout_sha256) == 64
    assert evidence.stderr_sha256 and len(evidence.stderr_sha256) == 64
    assert evidence.benchmark_score is None
    assert evidence.truthfulness["process_exit_success"] is True
    assert evidence.truthfulness["score_parsed"] is False
    assert evidence.truthfulness["score_claimed"] is False


def test_ade_bench_snowflake_execution_requires_explicit_credential_contract(tmp_path):
    repo, _ = _repo(tmp_path)
    evidence = ADEBenchRunner(
        ADEBenchSpec(repository=repo, database="snowflake", agent="sage"),
        runner=FakeRunner(),
        environ={},
    ).plan()
    assert evidence.status == "BLOCKED_EXTERNAL"
    assert any("credential_env" in reason for reason in evidence.blocked_reasons)