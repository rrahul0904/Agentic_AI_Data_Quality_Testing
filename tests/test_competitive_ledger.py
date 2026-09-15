from __future__ import annotations

import pytest

from agentic_data_platform.certification import build_competitive_ledger


SHA = "abcdef1234567890abcdef1234567890abcdef12"


def _statuses(ledger):
    return {record["capability"]: record["status"] for record in ledger["records"]}


def test_competitive_ledger_never_certifies_local_without_gate_evidence():
    ledger = build_competitive_ledger(SHA, local_gate_passed=False)
    statuses = _statuses(ledger)
    assert ledger["commit_sha"] == SHA
    assert ledger["superior"] is False
    assert statuses["ade_search_persistent_hybrid"] == "IMPLEMENTED_UNCERTIFIED"
    assert statuses["acp_fingerprint_permission_bridge"] == "IMPLEMENTED_UNCERTIFIED"
    assert statuses["snowflake_cortex_search_live"] == "NOT_RUN_EXTERNAL"
    assert statuses["ade_bench_upstream_native_ade_driver"] == "BLOCKED_EXTERNAL"
    assert ledger["truthfulness"]["ade_bench_score_claimed"] is False


def test_competitive_ledger_certifies_only_local_records_after_aggregate_gate():
    ledger = build_competitive_ledger(
        SHA,
        local_gate_passed=True,
        workflow={"workflow": "competitive-certification", "run_id": "123"},
    )
    for record in ledger["records"]:
        if record["scope"] != "benchmark" and record["status"] == "CERTIFIED_LOCAL":
            assert record["evidence"]["commit_sha"] == SHA
            assert record["evidence"]["local_gate_passed"] is True
            assert record["evidence"]["run_id"] == "123"
    statuses = _statuses(ledger)
    assert statuses["sql_antipattern_regression_1077"] == "CERTIFIED_LOCAL"
    assert statuses["column_lineage_regression_500"] == "CERTIFIED_LOCAL"
    assert statuses["snowflake_spcs_gpu_live"] == "NOT_RUN_EXTERNAL"
    assert statuses["cross_product_superiority_benchmark"] == "NOT_RUN_EXTERNAL"
    assert ledger["superior"] is False


def test_competitive_ledger_requires_exact_git_sha():
    with pytest.raises(ValueError, match="40-character Git SHA"):
        build_competitive_ledger("main", local_gate_passed=True)