from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentic_data_platform.dbt.runtime import DbtRuntime


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "dbt"
    root.mkdir()
    (root / "dbt_project.yml").write_text("name: demo\nversion: '1.0'\nprofile: demo\n")
    (root / "target").mkdir()
    return root


def test_dbt_runtime_builds_full_command_without_shell(tmp_path):
    root = _project(tmp_path)
    seen = {}

    def runner(argv, cwd, env, timeout):
        seen["argv"] = tuple(argv)
        seen["cwd"] = cwd
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    runtime = DbtRuntime(root, profiles_dir=tmp_path / "profiles", runner=runner)
    result = runtime.execute(
        "compile",
        select=["fact_orders", "+dim_guest"],
        exclude="tag:slow",
        target="dev",
        vars={"lookback": 7},
        state=tmp_path / "state",
        defer=True,
    )
    assert result["status"] == "PASS"
    assert seen["cwd"] == root
    assert "--select" in seen["argv"]
    assert "fact_orders +dim_guest" in seen["argv"]
    assert "--exclude" in seen["argv"]
    assert "--state" in seen["argv"]
    assert "--defer" in seen["argv"]


def test_dbt_runtime_artifact_failure_overrides_zero_exit(tmp_path):
    root = _project(tmp_path)
    (root / "target" / "run_results.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "unique_id": "model.demo.fact_orders",
                        "status": "error",
                        "message": "warehouse error",
                    }
                ]
            }
        )
    )

    def runner(argv, cwd, env, timeout):
        return subprocess.CompletedProcess(argv, 0, "success text", "")

    result = DbtRuntime(root, runner=runner).execute("build")
    assert result["exit_code"] == 0
    assert result["status"] == "FAIL"
    assert result["artifact_status_overrode_exit_code"] is True
    assert result["failed_nodes"][0]["unique_id"] == "model.demo.fact_orders"


def test_dbt_runtime_missing_executable_is_external_skip(tmp_path):
    root = _project(tmp_path)
    result = DbtRuntime(root, executable="definitely-not-installed").execute("parse")
    assert result["status"] == "SKIP_EXTERNAL"


def test_dbt_runtime_rejects_defer_without_state(tmp_path):
    root = _project(tmp_path)
    runtime = DbtRuntime(root)
    try:
        runtime.command("compile", defer=True)
    except ValueError as exc:
        assert "--defer requires --state" in str(exc)
    else:
        raise AssertionError("expected defer/state validation")
