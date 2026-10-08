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


def _module():
    return load_module(
        "rga_optimization_evaluator_test",
        ROOT / "scripts" / "rga_testbed" / "evaluate_optimization_experiment.py",
    )


def _report(
    *,
    concurrency: int = 10,
    direct_p95: float = 1000,
    semantic_p95: float = 1200,
    signature: str = "same",
    direct_queue: int = 0,
    semantic_queue: int = 0,
    direct_spill: int = 0,
    semantic_spill: int = 0,
    direct_scan: int = 1_000_000,
    semantic_scan: int = 800_000,
):
    results = []
    for variant in ("direct", "semantic"):
        for iteration in (1, 2):
            results.append(
                {
                    "status": "PASS",
                    "query_name": "q1",
                    "variant": variant,
                    "iteration": iteration,
                    "result_sha256": signature,
                }
            )
    return {
        "status": "PASS",
        "concurrency": concurrency,
        "result_parity": {"status": "PASS"},
        "results": results,
        "summary": {
            "variants": {
                "direct": {
                    "p95_client_elapsed_ms": direct_p95,
                    "bytes_scanned": direct_scan,
                    "queued_overload_ms": direct_queue,
                    "remote_spill_bytes": direct_spill,
                },
                "semantic": {
                    "p95_client_elapsed_ms": semantic_p95,
                    "bytes_scanned": semantic_scan,
                    "queued_overload_ms": semantic_queue,
                    "remote_spill_bytes": semantic_spill,
                },
            }
        },
    }


def test_optimization_evaluator_accepts_correct_faster_result():
    module = _module()
    before = [_report()]
    after = [
        _report(
            direct_p95=800,
            semantic_p95=900,
            direct_scan=800_000,
            semantic_scan=600_000,
        )
    ]
    result = module.evaluate(
        before,
        after,
        target_variant="both",
        min_p95_improvement_pct=10,
        max_scan_regression_pct=25,
    )
    assert result["decision"] == "ACCEPT"
    assert result["semantic_contract_preserved"] is True
    assert result["performance_regression_free"] is True
    assert result["performance_threshold_met"] is True
    assert len(result["comparisons"]) == 2


def test_optimization_evaluator_rejects_semantic_drift():
    module = _module()
    before = [_report(signature="before")]
    after = [_report(direct_p95=700, semantic_p95=800, signature="after")]
    result = module.evaluate(before, after)
    assert result["decision"] == "REJECT"
    assert result["semantic_contract_preserved"] is False
    assert any("result signature changed" in item for item in result["correctness_failures"])


def test_optimization_evaluator_rejects_queue_or_spill_regression():
    module = _module()
    before = [_report()]
    after = [
        _report(
            direct_p95=800,
            semantic_p95=900,
            direct_queue=10,
            semantic_spill=100,
        )
    ]
    result = module.evaluate(before, after)
    assert result["decision"] == "REJECT"
    assert result["performance_regression_free"] is False
    assert any("queue overload regressed" in item for item in result["regression_failures"])
    assert any("remote spill regressed" in item for item in result["regression_failures"])


def test_optimization_evaluator_marks_small_improvement_inconclusive():
    module = _module()
    before = [_report()]
    after = [_report(direct_p95=960, semantic_p95=1150)]
    result = module.evaluate(
        before,
        after,
        min_p95_improvement_pct=10,
    )
    assert result["decision"] == "INCONCLUSIVE"
    assert result["semantic_contract_preserved"] is True
    assert result["performance_regression_free"] is True
    assert result["performance_threshold_met"] is False


def test_optimization_evaluator_requires_matching_concurrency_sets():
    module = _module()
    try:
        module.evaluate(
            [_report(concurrency=5)],
            [_report(concurrency=10)],
        )
    except ValueError as exc:
        assert "concurrency sets must match exactly" in str(exc)
    else:
        raise AssertionError("before/after concurrency sets must match")
