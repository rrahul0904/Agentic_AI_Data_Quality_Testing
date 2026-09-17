from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _benchmark_modules():
    pack = load_module("rga_benchmark_pack_test", ROOT / "scripts" / "rga_testbed" / "generate_benchmark_pack.py")
    runner = load_module("rga_benchmark_runner_test", ROOT / "scripts" / "rga_testbed" / "run_snowflake_benchmark.py")
    return pack, runner


def test_benchmark_runner_is_fail_closed(tmp_path: Path):
    pack, runner = _benchmark_modules()
    pack.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    manifest = tmp_path / "manifest.json"
    assert runner.validate_request(manifest, 5, 3, confirm_live=False, dry_run=False) == [
        "Refusing live Snowflake benchmark without --confirm-live"
    ]
    assert runner.validate_request(manifest, 5, 3, confirm_live=False, dry_run=True) == []


def test_benchmark_plan_pairs_variants_and_iterations(tmp_path: Path):
    pack, runner = _benchmark_modules()
    pack.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    manifest_path = tmp_path / "manifest.json"
    manifest = runner.load_manifest(manifest_path)
    tasks = runner.build_plan(manifest_path, manifest, "both", iterations=4)
    assert len(tasks) == len(manifest["queries"]) * 2 * 4
    assert {task.variant for task in tasks} == {"direct", "semantic"}
    assert all(task.sql_file.exists() for task in tasks)
    payload = runner.dry_run_payload(manifest_path, tasks, concurrency=10)
    assert payload["status"] == "DRY_RUN"
    assert payload["concurrency"] == 10
    assert payload["task_count"] == len(tasks)


def test_benchmark_summary_reports_latency_scan_queue_and_spill():
    _, runner = _benchmark_modules()
    results = [
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "direct",
            "iteration": 1,
            "client_elapsed_ms": 100.0,
            "bytes_scanned": 1000,
            "queued_overload_time": 5,
            "bytes_spilled_to_remote_storage": 0,
        },
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "direct",
            "iteration": 2,
            "client_elapsed_ms": 200.0,
            "bytes_scanned": 2000,
            "queued_overload_time": 15,
            "bytes_spilled_to_remote_storage": 100,
        },
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "semantic",
            "iteration": 1,
            "client_elapsed_ms": 120.0,
            "bytes_scanned": 800,
            "queued_overload_time": 0,
            "bytes_spilled_to_remote_storage": 0,
        },
        {
            "status": "FAIL",
            "query_name": "q1",
            "variant": "semantic",
            "iteration": 2,
            "client_elapsed_ms": 50.0,
            "error": "synthetic failure",
        },
    ]
    summary = runner.summarize(results, wall_seconds=2.0)
    assert summary["total"] == 4
    assert summary["passed"] == 3
    assert summary["failed"] == 1
    assert summary["throughput_qps"] == 2.0
    assert summary["variants"]["direct"]["p50_client_elapsed_ms"] == 150.0
    assert summary["variants"]["direct"]["bytes_scanned"] == 3000
    assert summary["variants"]["direct"]["queued_overload_ms"] == 20
    assert summary["variants"]["direct"]["remote_spill_bytes"] == 100
    assert summary["variants"]["semantic"]["passed"] == 1


def test_connection_contract_tags_benchmark_sessions():
    _, runner = _benchmark_modules()
    kwargs = runner.connection_kwargs(
        {
            "SNOWFLAKE_ACCOUNT": "acct",
            "SNOWFLAKE_USER": "bench",
            "SNOWFLAKE_WAREHOUSE": "BENCH_WH",
            "SNOWFLAKE_PASSWORD": "secret",
        },
        "RGA_SEMANTIC_BENCHMARK:run:direct:q1",
    )
    assert kwargs["warehouse"] == "BENCH_WH"
    assert kwargs["database"] == "RGA_SYNTHETIC_TESTBED"
    assert kwargs["session_parameters"]["QUERY_TAG"].startswith("RGA_SEMANTIC_BENCHMARK")
