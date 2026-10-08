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


def _manifest():
    return {
        "acceptance": {"target_p95_ms": 5000, "max_remote_spill_bytes": 0},
        "queries": [
            {
                "id": "monthly_loss_ratio_by_cedant",
                "metrics": ["CEDED_LOSS_RATIO"],
                "dimensions": ["CEDANT_NAME", "PERIOD_MONTH"],
            }
        ],
    }


def _report(variant: str, elapsed: float, bytes_scanned: int, queue: int = 0, spill: int = 0):
    return {
        "concurrency": 10,
        "results": [
            {
                "status": "PASS",
                "query_name": "monthly_loss_ratio_by_cedant",
                "variant": variant,
                "client_elapsed_ms": elapsed,
                "bytes_scanned": bytes_scanned,
                "queued_overload_time": queue,
                "bytes_spilled_to_remote_storage": spill,
            },
            {
                "status": "PASS",
                "query_name": "monthly_loss_ratio_by_cedant",
                "variant": variant,
                "client_elapsed_ms": elapsed + 100,
                "bytes_scanned": bytes_scanned,
                "queued_overload_time": queue,
                "bytes_spilled_to_remote_storage": spill,
            },
        ],
    }


def test_semantic_workload_recommends_materialization_from_evidence():
    module = load_module("rga_workload_semantic_test", ROOT / "scripts" / "rga_testbed" / "analyze_workload.py")
    result = module.build_analysis(_manifest(), [_report("semantic", 7000, 1_000_000_000)])
    rec = result["recommendations"][0]
    assert rec["candidate"] == "semantic_view_materialization"
    assert rec["requires_benchmark_validation"] is True
    assert result["fingerprints"][0]["executions"] == 2


def test_direct_workload_recommends_physical_optimization_and_concurrency():
    module = load_module("rga_workload_direct_test", ROOT / "scripts" / "rga_testbed" / "analyze_workload.py")
    result = module.build_analysis(_manifest(), [_report("direct", 6500, 2_000_000_000, queue=500, spill=1024)])
    rec = result["recommendations"][0]
    assert "underlying_mart_aggregate_or_dynamic_table" in rec["candidate"]
    assert "warehouse_concurrency" in rec["candidate"]
    assert "warehouse_size_or_query_shape" in rec["candidate"]
    assert rec["confidence"] == "high"


def test_fast_low_cost_workload_is_not_optimized_without_evidence():
    module = load_module("rga_workload_noop_test", ROOT / "scripts" / "rga_testbed" / "analyze_workload.py")
    result = module.build_analysis(_manifest(), [_report("semantic", 400, 0)])
    assert result["recommendations"] == []
    assert "not automatic physical mutations" in result["policy"]
