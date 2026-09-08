from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agentic_data_platform.agents.scenarios import FailureScenario


@dataclass(frozen=True)
class RecoveryAction:
    system: str
    operation: str
    target: str
    arguments: dict[str, Any]
    risk: str
    requires_approval: bool = True


@dataclass(frozen=True)
class SelectiveRecoveryPlan:
    airflow_actions: tuple[RecoveryAction, ...]
    dbt_selector: str | None
    dbt_command: str | None
    quality_rechecks: tuple[str, ...]
    certification_targets: tuple[str, ...]
    bounded: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "airflow_actions": [asdict(item) for item in self.airflow_actions],
            "dbt_selector": self.dbt_selector,
            "dbt_command": self.dbt_command,
            "quality_rechecks": list(self.quality_rechecks),
            "certification_targets": list(self.certification_targets),
            "bounded": self.bounded,
        }


def _airflow_dag(path: tuple[str, ...]) -> str | None:
    for asset in path:
        if asset.startswith("airflow."):
            return asset.removeprefix("airflow.")
    return None


def _first_dbt_asset(path: tuple[str, ...]) -> str | None:
    for asset in path:
        simple = asset.rsplit(".", 1)[-1]
        if simple.startswith(("stg_", "int_", "fact_", "dim_", "mart_")):
            return simple
    return None


def build_selective_recovery_plan(
    scenario: FailureScenario,
    blast_radius: tuple[str, ...] | list[str],
) -> SelectiveRecoveryPlan:
    dag_id = _airflow_dag(scenario.pipeline_path)
    root = scenario.expected_root_cause
    signals = scenario.signals
    airflow_actions: list[RecoveryAction] = []

    if dag_id and root in {
        "WATERMARK_ADVANCED_BEYOND_EXTRACT",
        "BUSINESS_COMPLETENESS_ANOMALY",
        "AIRFLOW_RETRY_DUPLICATE_LOAD",
        "AIRFLOW_TASK_FAILURE",
        "CDC_EVENT_GAP",
        "OUT_OF_ORDER_EVENT",
        "SNOWFLAKE_PARTIAL_LOAD",
    }:
        start = signals.get("extracted_max_timestamp") or signals.get("missing_sequence_start")
        end = signals.get("persisted_watermark") or signals.get("missing_sequence_end")
        airflow_actions.append(RecoveryAction(
            system="airflow",
            operation="bounded_backfill" if start is not None and end is not None else "rerun_dag",
            target=dag_id,
            arguments={
                "dag_id": dag_id,
                "start": start,
                "end": end,
                "reset_watermark": root == "WATERMARK_ADVANCED_BEYOND_EXTRACT",
                "dry_run_first": True,
            },
            risk="MUTATING",
        ))

    dbt_root = _first_dbt_asset(scenario.pipeline_path)
    dbt_selector = f"{dbt_root}+" if dbt_root else None
    if root == "DBT_COMPILATION_FAILURE":
        dbt_command = f"dbt compile --select {dbt_selector}" if dbt_selector else "dbt compile"
    else:
        dbt_command = f"dbt build --select {dbt_selector}" if dbt_selector else None

    impact = tuple(dict.fromkeys(str(item) for item in blast_radius))
    quality_rechecks = (
        f"recheck:{scenario.expected_first_divergence}",
        f"quality:{scenario.affected_asset}",
        f"business_metric:{scenario.business_concept}",
    )
    certification_targets = tuple(dict.fromkeys((scenario.affected_asset, *impact)))
    return SelectiveRecoveryPlan(
        airflow_actions=tuple(airflow_actions),
        dbt_selector=dbt_selector,
        dbt_command=dbt_command,
        quality_rechecks=quality_rechecks,
        certification_targets=certification_targets,
    )
