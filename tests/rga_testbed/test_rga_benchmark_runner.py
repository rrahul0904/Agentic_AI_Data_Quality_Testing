from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
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
            "partitions_scanned": 5,
            "partitions_total": 10,
            "query_acceleration_bytes_scanned": 0,
            "query_acceleration_upper_limit_scale_factor": 2,
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
            "partitions_scanned": 7,
            "partitions_total": 10,
            "query_acceleration_bytes_scanned": 100,
            "query_acceleration_upper_limit_scale_factor": 4,
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
            "partitions_scanned": 3,
            "partitions_total": 10,
            "query_acceleration_bytes_scanned": 50,
            "query_acceleration_upper_limit_scale_factor": 1,
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
    assert summary["variants"]["direct"]["partitions_scanned"] == 12
    assert summary["variants"]["direct"]["partitions_total"] == 20
    assert summary["variants"]["direct"]["query_acceleration_bytes_scanned"] == 100
    assert summary["variants"]["direct"]["query_acceleration_upper_limit_scale_factor"] == 4
    assert summary["variants"]["semantic"]["partitions_scanned"] == 3
    assert summary["variants"]["semantic"]["query_acceleration_upper_limit_scale_factor"] == 1
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


def test_canonical_result_is_order_independent_and_case_normalized():
    _, runner = _benchmark_modules()
    left = runner.canonical_result(
        ["cedant_name", "ceded_loss_ratio"],
        [("B", 0.2), ("A", 0.1)],
    )
    right = runner.canonical_result(
        ["CEDANT_NAME", "CEDED_LOSS_RATIO"],
        [("A", 0.1), ("B", 0.2)],
    )
    assert left["result_sha256"] == right["result_sha256"]
    assert left["row_count"] == 2
    assert left["columns"] == ["CEDANT_NAME", "CEDED_LOSS_RATIO"]


def test_result_parity_passes_when_direct_and_semantic_match():
    _, runner = _benchmark_modules()
    signature = runner.canonical_result(["X"], [(1,)])["result_sha256"]
    results = [
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "direct",
            "iteration": 1,
            "result_sha256": signature,
            "row_count": 1,
        },
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "semantic",
            "iteration": 1,
            "result_sha256": signature,
            "row_count": 1,
        },
    ]
    parity = runner.result_parity(results, "both")
    assert parity["status"] == "PASS"
    assert parity["failed_queries"] == 0
    assert parity["queries"]["q1"]["status"] == "PASS"


def test_result_parity_fails_on_semantic_drift():
    _, runner = _benchmark_modules()
    direct = runner.canonical_result(["X"], [(1,)])["result_sha256"]
    semantic = runner.canonical_result(["X"], [(2,)])["result_sha256"]
    results = [
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "direct",
            "iteration": 1,
            "result_sha256": direct,
            "row_count": 1,
        },
        {
            "status": "PASS",
            "query_name": "q1",
            "variant": "semantic",
            "iteration": 1,
            "result_sha256": semantic,
            "row_count": 1,
        },
    ]
    parity = runner.result_parity(results, "both")
    assert parity["status"] == "FAIL"
    assert parity["failed_queries"] == 1
    assert "differ" in parity["queries"]["q1"]["reason"]


def test_result_parity_fails_when_repeated_iterations_are_not_stable():
    _, runner = _benchmark_modules()
    first = runner.canonical_result(["X"], [(1,)])["result_sha256"]
    second = runner.canonical_result(["X"], [(2,)])["result_sha256"]
    results = [
        {"status": "PASS", "query_name": "q1", "variant": "direct", "iteration": 1, "result_sha256": first, "row_count": 1},
        {"status": "PASS", "query_name": "q1", "variant": "direct", "iteration": 2, "result_sha256": second, "row_count": 1},
        {"status": "PASS", "query_name": "q1", "variant": "semantic", "iteration": 1, "result_sha256": first, "row_count": 1},
        {"status": "PASS", "query_name": "q1", "variant": "semantic", "iteration": 2, "result_sha256": first, "row_count": 1},
    ]
    parity = runner.result_parity(results, "both")
    assert parity["status"] == "FAIL"
    assert "changed across repeated iterations" in parity["queries"]["q1"]["reason"]


def test_telemetry_retries_until_query_history_is_visible():
    _, runner = _benchmark_modules()

    class Cursor:
        def __init__(self):
            self.calls = 0
            self.description = [("QUERY_ID",), ("TOTAL_ELAPSED_TIME",)]

        def execute(self, sql, params):
            self.calls += 1

        def fetchone(self):
            if self.calls < 3:
                return None
            return ("qid", 123)

    cursor = Cursor()
    telemetry = runner._telemetry(cursor, "qid", attempts=5, delay_seconds=0)
    assert telemetry["telemetry_status"] == "FOUND"
    assert telemetry["telemetry_attempts"] == 3
    assert telemetry["query_id"] == "qid"
    assert telemetry["total_elapsed_time"] == 123
