from pathlib import Path
import json

from agentic_data_platform.dbt.advanced import (
    compiled_sql_review, incremental_analysis, leaf_model_candidates, macro_analysis,
    snapshot_analysis, source_freshness_configuration, state_compare,
)
from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.platform.airflow_ops import (
    backfill_analysis, failure_lab, pipeline_health, retry_analysis, root_cause_from_error,
)
from agentic_data_platform.quality.data_diff import (
    data_diff_report, duckdb_demo_diff, schema_diff,
)
from agentic_data_platform.quality.store import QualityResult, SQLiteQualityStore
from agentic_data_platform.remediation.proposals import (
    propose_airflow_retry, propose_dbt_tests, propose_quality_rule, propose_sql_repair,
)
from agentic_data_platform.platform.root_cause import asset_health, platform_root_cause


ROOT = Path(__file__).resolve().parents[1]
HOSPITALITY = ROOT / "hospitality-snowflake-data-platform"


def graph() -> DbtManifestGraph:
    return DbtManifestGraph(DbtArtifacts.load(HOSPITALITY / "dbt" / "target"))


def test_data_diff_reports_changed_missing_and_extra_rows():
    source = [{"id": 1, "amount": 10.0}, {"id": 2, "amount": 20.0}, {"id": 3, "amount": 30.0}]
    target = [{"id": 1, "amount": 10.0}, {"id": 2, "amount": 25.0}, {"id": 4, "amount": 40.0}]
    result = data_diff_report(source, target, ["id"], aggregate_columns=["amount"])
    assert result["status"] == "FAIL"
    assert result["rows"]["counts"] == {"matches": 1, "missing": 1, "extra": 1, "changed": 1}
    assert result["hash"]["changed_keys"] == [[2]]
    assert result["aggregates"][0]["difference"] == 15.0


def test_schema_diff_is_fail_closed():
    result = schema_diff({"id": "INTEGER", "amount": "FLOAT"}, {"id": "INTEGER", "amount": "STRING", "extra": "TEXT"})
    assert result["status"] == "FAIL"
    assert result["extra_columns"] == ["extra"]
    assert result["type_mismatches"][0]["column"] == "amount"


def test_duckdb_demo_executes_real_local_fixture():
    result = duckdb_demo_diff()
    assert result["mode"] == "LOCAL_SIMULATION"
    assert result["source"].startswith("duckdb:")
    assert result["rows"]["counts"]["changed"] == 1
    assert result["rows"]["counts"]["missing"] == 1
    assert result["rows"]["counts"]["extra"] == 1


def test_advanced_dbt_intelligence_reads_real_manifest(tmp_path):
    current = graph()
    incrementals = incremental_analysis(current)
    snapshots = snapshot_analysis(current)
    macros = macro_analysis(current)
    freshness = source_freshness_configuration(current)
    leaves = leaf_model_candidates(current)
    review = compiled_sql_review(current, limit=5)
    assert incrementals["count"] >= 1
    assert snapshots["count"] == 4
    assert macros["count"] >= 1
    assert freshness["count"] >= 1
    assert isinstance(leaves["candidates"], list)
    assert review["models_reviewed"] <= 5

    previous_path = tmp_path / "manifest.json"
    previous_path.write_text(json.dumps(current.artifacts.manifest))
    assert state_compare(current, previous_path)["changed_nodes"] == []


def test_airflow_operational_analysis_and_failure_lab():
    retries = retry_analysis(HOSPITALITY)
    backfill = backfill_analysis(HOSPITALITY)
    health = pipeline_health(HOSPITALITY)
    lab = failure_lab()
    assert retries["dag_count"] == 57
    assert backfill["mode"] == "STATIC"
    assert 0 <= health["score"] <= 100
    assert lab["diagnosis"]["cause"] == "WAREHOUSE_PERMISSION"
    assert root_cause_from_error("connection refused by postgres")["cause"] == "CONNECTION_FAILURE"


def test_proposals_never_apply_changes():
    current = graph()
    dbt = propose_dbt_tests(current, limit=3)
    sql = propose_sql_repair("SELECT * FROM orders", "snowflake")
    airflow = propose_airflow_retry(HOSPITALITY, "oracle_reservation_ingest")
    quality = propose_quality_rule("CORE.FACT_RESERVATION", "unique")
    assert dbt["applied"] is False
    assert sql["applied"] is False
    assert airflow["applied"] is False
    assert quality["applied"] is False
    assert all(item["status"] == "PROPOSED" for item in dbt["proposals"])


def test_cross_system_root_cause_uses_quality_evidence(tmp_path):
    database = tmp_path / "quality.db"
    store = SQLiteQualityStore(database)
    store.initialize()
    run_id = store.start_run("failure")
    store.save_result(QualityResult(
        check_id="reservation_row_count_parity", run_id=run_id, system="snowflake", layer="RAW",
        asset="RAW.ORACLE_RESERVATION", check_type="row_count", severity="ERROR", status="FAIL",
        observed_value=9998, expected_value=10000,
    ))
    store.complete_run(run_id, "FAIL")
    diagnosis = platform_root_cause(HOSPITALITY, database, asset="reservation")
    assert diagnosis["status"] == "DIAGNOSED"
    assert any(item["cause"] == "DATA_QUALITY_FAILURE" for item in diagnosis["candidate_causes"])
    health = asset_health(HOSPITALITY, database, "stg_oracle_reservation")
    assert 0 <= health["score"] <= 100
