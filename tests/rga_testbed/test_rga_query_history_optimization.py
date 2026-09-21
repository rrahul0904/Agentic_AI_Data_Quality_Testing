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


def _collector():
    return load_module(
        "rga_query_history_test",
        ROOT / "scripts" / "rga_testbed" / "collect_query_history.py",
    )


def _analyzer():
    return load_module(
        "rga_history_analyzer_test",
        ROOT / "scripts" / "rga_testbed" / "analyze_workload.py",
    )


def _manifest():
    return {
        "acceptance": {"target_p95_ms": 5000, "max_remote_spill_bytes": 0},
        "queries": [
            {
                "id": "q1",
                "metrics": ["TOTAL_CEDED_PREMIUM"],
                "dimensions": ["TREATY_NAME"],
            }
        ],
    }


def _benchmark_report(**overrides):
    row = {
        "status": "PASS",
        "query_name": "q1",
        "variant": "direct",
        "query_id": "qid-benchmark",
        "client_elapsed_ms": 7000,
        "bytes_scanned": 2_000_000_000,
        "partitions_scanned": 100,
        "partitions_total": 100,
        "queued_overload_time": 0,
        "bytes_spilled_to_remote_storage": 0,
        "query_acceleration_bytes_scanned": 0,
        "query_acceleration_upper_limit_scale_factor": 4,
        "query_hash": "hash-1",
        "query_parameterized_hash": "phash-1",
    }
    row.update(overrides)
    return {"concurrency": 10, "results": [row, dict(row)]}


def test_query_history_collector_is_fail_closed():
    module = _collector()
    assert module.validate_request(14, 1000, confirm=False, dry_run=False) == [
        "Refusing live Query History collection without --confirm"
    ]
    assert module.validate_request(14, 1000, confirm=False, dry_run=True) == []
    assert module.validate_request(15, 1000, confirm=True, dry_run=False) == [
        "days must be between 1 and 14 so QAS eligibility estimates remain actionable"
    ]


def test_query_shape_extracts_tables_and_predicates_without_literal_values():
    module = _collector()
    shape = module.query_shape(
        """
        select *
        from RGA_SYNTHETIC_TESTBED.MART.REINSURANCE_PERFORMANCE r
        join RGA_SYNTHETIC_TESTBED.CORE.DIM_TREATY t
          on r.treaty_id = t.treaty_id
        where r.period_month between '2026-01-01' and '2026-06-01'
          and r.cedant_id in ('A', 'B')
          and t.treaty_type = 'YRT'
        group by 1
        """
    )
    assert "RGA_SYNTHETIC_TESTBED.MART.REINSURANCE_PERFORMANCE" in shape["tables"]
    assert "RGA_SYNTHETIC_TESTBED.CORE.DIM_TREATY" in shape["tables"]
    predicate_columns = {item["column"] for item in shape["predicates"]}
    assert {"PERIOD_MONTH", "CEDANT_ID", "TREATY_TYPE"}.issubset(predicate_columns)
    assert shape["has_selective_predicate_shape"] is True
    assert "2026" not in str(shape)
    assert "YRT" not in str(shape)


def test_collection_plan_excludes_query_text_by_default():
    module = _collector()
    plan = module.collection_plan(
        days=14,
        limit=1000,
        query_tag_prefix="RGA_",
        database="RGA_SYNTHETIC_TESTBED",
        include_query_text=False,
    )
    assert plan["status"] == "DRY_RUN"
    assert plan["include_query_text"] is False
    assert "Query text is excluded by default" in plan["privacy"]


def test_benchmark_qas_signal_generates_estimator_not_mutation():
    module = _analyzer()
    result = module.build_analysis(_manifest(), [_benchmark_report()])
    rec = result["recommendations"][0]
    assert "query_acceleration_service" in rec["candidates"]
    qas = next(item for item in rec["experiments"] if item["type"] == "query_acceleration_service")
    assert qas["representative_query_id"] == "qid-benchmark"
    assert "SYSTEM$ESTIMATE_QUERY_ACCELERATION" in qas["estimate_sql"]
    assert rec["automatic_mutation_allowed"] is False


def test_history_equality_predicates_with_poor_pruning_generate_diagnostics_only():
    module = _analyzer()
    queries = []
    for index in range(3):
        queries.append(
            {
                "query_id": f"qid-{index}",
                "query_hash": "qh",
                "query_parameterized_hash": "pqh",
                "total_elapsed_time": 6000 + index,
                "bytes_scanned": 1_000_000_000,
                "partitions_scanned": 90,
                "partitions_total": 100,
                "queued_overload_time": 0,
                "bytes_spilled_to_remote_storage": 0,
                "query_acceleration_bytes_scanned": 0,
                "query_acceleration_upper_limit_scale_factor": 0,
                "shape": {
                    "tables": ["RGA_SYNTHETIC_TESTBED.MART.REINSURANCE_PERFORMANCE"],
                    "predicates": [
                        {"column": "CEDANT_ID", "operator": "="},
                        {"column": "PERIOD_MONTH", "operator": "BETWEEN"},
                    ],
                },
            }
        )
    history = {"query_count": 3, "queries": queries}
    result = module.build_analysis(_manifest(), [_benchmark_report(query_acceleration_upper_limit_scale_factor=0)], history)
    experiments = result["query_history"]["experiments"]
    clustering = next(item for item in experiments if item["type"] == "clustering_diagnostic")
    search = next(item for item in experiments if item["type"] == "search_optimization_cost_estimate")

    assert "SYSTEM$CLUSTERING_INFORMATION" in clustering["diagnostic_sql"]
    assert clustering["automatic_mutation_allowed"] is False
    assert clustering["mutation_sql"].startswith("ALTER TABLE")
    assert "SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS" in search["estimate_sql"]
    assert search["columns"] == ["CEDANT_ID"]
    assert search["automatic_mutation_allowed"] is False


def test_history_without_predicates_never_recommends_clustering_or_search_optimization():
    module = _analyzer()
    history = {
        "query_count": 4,
        "queries": [
            {
                "query_id": f"qid-{index}",
                "query_parameterized_hash": "pqh",
                "total_elapsed_time": 8000,
                "bytes_scanned": 1_000_000_000,
                "partitions_scanned": 100,
                "partitions_total": 100,
                "shape": {
                    "tables": ["RGA_SYNTHETIC_TESTBED.MART.REINSURANCE_PERFORMANCE"],
                    "predicates": [],
                },
            }
            for index in range(4)
        ],
    }
    result = module.build_analysis(_manifest(), [_benchmark_report(query_acceleration_upper_limit_scale_factor=0)], history)
    types = {item["type"] for item in result["query_history"]["experiments"]}
    assert "clustering_diagnostic" not in types
    assert "search_optimization_cost_estimate" not in types
