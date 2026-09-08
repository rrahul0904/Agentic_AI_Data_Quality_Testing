from __future__ import annotations

from pathlib import Path

import pytest

from agentic_data_platform.airflow_compat import AirflowAdapter, AirflowControlPlane
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


DAG_SOURCE = """
from airflow.sdk import DAG, Asset, task, Variable
from airflow.providers.standard.sensors.filesystem import FileSensor
from airflow.providers.standard.operators.empty import EmptyOperator

landing = Asset("s3://landing/reservations")

with DAG(
    dag_id="reservation_pipeline",
    schedule=landing,
    catchup=False,
    default_args={"retries": 3},
) as dag:
    wait = FileSensor(task_id="wait_source", filepath="/tmp/source", mode="poke")
    load = EmptyOperator(
        task_id="load",
        pool="warehouse",
        queue="etl",
    )
    token = Variable.get("api_token")
    wait >> load

@task
def mapped(value):
    return value

mapped.expand(value=[1, 2, 3])
"""


def _project(tmp_path: Path) -> Path:
    dags = tmp_path / "airflow" / "dags"
    dags.mkdir(parents=True)
    (dags / "reservation.py").write_text(DAG_SOURCE)
    return tmp_path


def test_airflow3_static_control_plane_detects_modern_surfaces(tmp_path):
    project = _project(tmp_path)
    control = AirflowControlPlane(project)

    inventory = control.inventory()
    assert inventory["compatibility"]["inferred_semantics"] == "3.x"
    assert inventory["dynamic_mapping_files"] == 1

    assets = control.asset_report()
    assert assets["items"][0]["name"] == "s3://landing/reservations"

    capacity = control.capacity_report()
    assert capacity["pools"] == ["warehouse"]
    assert capacity["queues"] == ["etl"]

    mapping = control.mapping_report()
    assert mapping["mapping_count"] >= 1
    assert mapping["risk"] == "LOW"
    assert any(item["static_cardinality"] == 3 for item in mapping["mapping_calls"])

    deferrable = control.deferrable_report()
    assert deferrable["inefficient_sensors"]

    quality = control.quality_scan()
    assert any(item["rule_id"] == "AIRFLOW_DYNAMIC_MAP_REVIEW" for item in quality["findings"])
    assert any(item["rule_id"] == "AIRFLOW_SENSOR_WORKER_SLOT" for item in quality["findings"])


def test_airflow_security_never_returns_secret_values(tmp_path):
    project = _project(tmp_path)
    path = project / "airflow" / "dags" / "bad_secret.py"
    path.write_text('password = "super-secret-value"\n')
    report = AirflowControlPlane(project).security_report()
    assert report["status"] == "FAIL"
    assert report["secret_values_returned"] is False
    assert "super-secret-value" not in str(report)


def test_airflow_runtime_adapter_versioning_and_mock_transport():
    calls = []

    def transport(method, url, body, headers):
        calls.append((method, url, body, headers))
        return {"status": "PASS", "url": url}

    adapter = AirflowAdapter("https://airflow.example", version="3.3.0", token="secret", transport=transport)
    result = adapter.dags(limit=5)
    assert result["status"] == "PASS"
    assert "/api/v2/dags?limit=5" in calls[0][1]
    assert calls[0][3]["Authorization"].startswith("Bearer ")

    with pytest.raises(PermissionError):
        adapter.trigger("reservation_pipeline")

    dry = adapter.trigger("reservation_pipeline", dry_run=True)
    assert dry["status"] == "DRY_RUN"


def test_airflow_runtime_without_endpoint_is_honest_skip():
    adapter = AirflowAdapter(version="3.3.0")
    result = adapter.health()
    assert result["status"] == "SKIP_EXTERNAL"


def test_airflow_tools_are_governed_and_mutations_require_builder_approval(tmp_path):
    project = _project(tmp_path)
    registry = build_tool_registry()

    for name in (
        "airflow_graph",
        "airflow_asset_inventory",
        "airflow_dynamic_mapping_analysis",
        "airflow_bundle_security",
        "airflow_sdk_compatibility",
        "airflow_secret_risk",
        "airflow_xcom_analysis",
        "airflow_capacity_plan",
        "airflow_quality_scan",
        "airflow_doctor",
    ):
        assert registry.describe(name).risk.value == "read_only"

    definition = registry.describe("airflow_trigger")
    request = ToolRequest(
        "airflow_trigger",
        "airflow_trigger",
        Environment.DEV,
        definition.risk,
        args={"project": str(project), "dag_id": "reservation_pipeline"},
    )
    with pytest.raises(PermissionError):
        registry.invoke(ToolInvocation(request, run_id="test", actor_mode=ActorMode.ANALYST))
    with pytest.raises(PermissionError):
        registry.invoke(ToolInvocation(request, run_id="test", actor_mode=ActorMode.BUILDER))

    dry_request = ToolRequest(
        "airflow_trigger",
        "airflow_trigger",
        Environment.DEV,
        definition.risk,
        args={"project": str(project), "dag_id": "reservation_pipeline"},
    )
    dry = registry.invoke(
        ToolInvocation(
            dry_request,
            run_id="test",
            actor_mode=ActorMode.BUILDER,
            approved=True,
            dry_run=True,
        )
    )
    assert dry["status"] == "DRY_RUN"


def test_airflow_static_semantics_surface(tmp_path):
    dags = tmp_path / "airflow" / "dags"
    dags.mkdir(parents=True)
    (dags / "semantics.py").write_text(
        "from airflow.sdk import DAG, Asset\n"
        "from airflow.providers.standard.operators.python import BranchPythonOperator, ShortCircuitOperator\n"
        "asset = Asset('s3://raw/reservation')\n"
        "def failed(context): pass\n"
        "with DAG(dag_id='semantic_dag', schedule=asset, catchup=False, max_active_runs=2, on_failure_callback=failed) as dag:\n"
        "    branch = BranchPythonOperator(task_id='branch', python_callable=lambda: 'work', retries=12, trigger_rule='all_done', pool='etl')\n"
        "    gate = ShortCircuitOperator(task_id='gate', python_callable=lambda: True, depends_on_past=True, outlets=[asset])\n"
        "branch.expand_kwargs([{'python_callable': 'a'}, {'python_callable': 'b'}])\n"
    )
    control = AirflowControlPlane(tmp_path)
    report = control.static_semantics()
    assert report["status"] == "PASS"
    assert report["counts"]["callbacks"] >= 1
    assert report["counts"]["branches"] >= 1
    assert report["counts"]["short_circuits"] >= 1
    settings = [item for record in report["records"] for item in record["settings"]]
    assert any(item["key"] == "max_active_runs" and item["value"] == 2 for item in settings)
    mapping = control.mapping_report()
    assert any(item["static_cardinality"] == 2 for item in mapping["mapping_calls"])
    rules = {item["rule_id"] for item in control.quality_scan()["findings"]}
    assert "AIRFLOW_EXCESSIVE_RETRIES" in rules
    assert "AIRFLOW_TRIGGER_RULE_RISK" in rules
    assert "AIRFLOW_DEPENDS_ON_PAST" in rules
