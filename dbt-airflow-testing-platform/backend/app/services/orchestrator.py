"""Coordinates one Test Run across an arbitrary set of dbt jobs (local or
dbt Cloud) and Airflow DAGs -- all executed concurrently, all results
persisted, an overall PASSED/FAILED/ERROR status computed at the end.

This generalizes the single-project-single-DAG v0.1 orchestrator: a run now
belongs to at most one dbt project and/or one Airflow project, but can
exercise *several* jobs/DAGs from each in one go (the "one job or multiple
jobs" selection the UI exposes).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import (
    AirflowDagRun,
    AirflowProject,
    AirflowTaskResult,
    Artifact,
    DbtJob,
    DbtJobRun,
    DbtProject,
    DbtTestResult,
    TestRun,
)
from .airflow_client import AirflowClient
from .dbt_runner import run_dbt_build

logger = logging.getLogger("ade.orchestrator")

_CLOUD_STATUS_TO_RESULT = {"success": "PASSED", "error": "FAILED", "cancelled": "FAILED", "UNREACHABLE": "ERROR"}


def _run_local_dbt_job(project: DbtProject, select_str: str | None):
    return run_dbt_build(
        project_dir=project.project_dir,
        profiles_dir=project.profiles_dir,
        target=project.dbt_target,
        dbt_executable=f"{project.venv_path}/bin/dbt",
        select=select_str,
    )


def _run_cloud_dbt_job(project: DbtProject, dbt_cloud_job_id: str):
    from .dbt_cloud_client import DbtCloudClient

    client = DbtCloudClient(
        host=project.dbt_cloud_host,
        account_id=project.dbt_cloud_account_id,
        api_token=project.dbt_cloud_api_token,
        timeout_seconds=settings.dbt_cloud_request_timeout_seconds,
    )
    return client.run_job_to_completion(
        dbt_cloud_job_id,
        poll_interval_seconds=settings.poll_interval_seconds,
        timeout_seconds=settings.run_timeout_seconds,
    )


def _run_airflow_dag(project: AirflowProject, dag_id: str):
    client = AirflowClient(
        base_url=project.base_url,
        username=project.admin_username,
        password=project.admin_password,
        timeout_seconds=settings.airflow_request_timeout_seconds,
    )
    return client.run_dag_to_completion(
        dag_id=dag_id,
        poll_interval_seconds=settings.poll_interval_seconds,
        timeout_seconds=settings.run_timeout_seconds,
    )


async def _run_one_dbt_job(dbt_project: DbtProject, label: str, mode: str, select_str: str | None, dbt_job_id: str | None, cloud_job_id: str | None):
    if mode == "local":
        outcome = await asyncio.to_thread(_run_local_dbt_job, dbt_project, select_str)
    else:
        outcome = await asyncio.to_thread(_run_cloud_dbt_job, dbt_project, cloud_job_id)
    return ("dbt", mode, label, dbt_job_id, outcome)


async def _run_one_dag(airflow_project: AirflowProject, dag_id: str):
    outcome = await asyncio.to_thread(_run_airflow_dag, airflow_project, dag_id)
    return ("airflow", dag_id, outcome)


async def execute_test_run(run_id: str) -> None:
    db: Session = SessionLocal()
    try:
        run = db.get(TestRun, run_id)
        if run is None:
            logger.error("Test run %s vanished before execution", run_id)
            return

        run.status = "RUNNING"
        db.commit()

        dbt_project = db.get(DbtProject, run.dbt_project_id) if run.dbt_project_id else None
        airflow_project = db.get(AirflowProject, run.airflow_project_id) if run.airflow_project_id else None

        dbt_job_specs: list[tuple[str, str, str | None, str | None, str | None]] = []
        if dbt_project is not None:
            if run.dbt_job_ids:
                jobs = db.scalars(select(DbtJob).where(DbtJob.id.in_(run.dbt_job_ids))).all()
                for j in jobs:
                    dbt_job_specs.append((j.name, dbt_project.execution_mode, j.select_str, j.id, j.dbt_cloud_job_id))
            elif run.dbt_adhoc_select and dbt_project.execution_mode == "local":
                dbt_job_specs.append((run.dbt_adhoc_select, "local", run.dbt_adhoc_select, None, None))
            else:
                dbt_job_specs.append(("(whole project)", dbt_project.execution_mode, None, None, None))

        airflow_dag_ids = run.airflow_dag_ids or []

        tasks = [_run_one_dbt_job(dbt_project, *spec) for spec in dbt_job_specs]
        tasks += [_run_one_dag(airflow_project, dag_id) for dag_id in airflow_dag_ids]

        results = await asyncio.gather(*tasks) if tasks else []

        overall_ok = True
        for item in results:
            if item[0] == "dbt":
                _, mode, label, dbt_job_id, outcome = item

                job_run = DbtJobRun(run_id=run.id, dbt_job_id=dbt_job_id, label=label, mode=mode)
                db.add(job_run)
                db.flush()

                if mode == "local":
                    job_run.status = outcome.overall_status
                    for row in outcome.rows:
                        db.add(
                            DbtTestResult(
                                dbt_job_run_id=job_run.id,
                                unique_id=row.unique_id,
                                node_kind=row.node_kind,
                                name=row.name,
                                status=row.status,
                                execution_time=row.execution_time,
                                message=row.message,
                                relation_name=row.relation_name,
                            )
                        )
                    if outcome.run_results_json:
                        db.add(Artifact(run_id=run.id, kind=f"dbt_run_results:{label}", content=outcome.run_results_json))
                    if not outcome.stdout_tail == "" and job_run.status == "ERROR":
                        db.add(Artifact(run_id=run.id, kind=f"dbt_stdout_tail:{label}", content=outcome.stdout_tail))
                else:
                    job_run.dbt_cloud_run_id = outcome.run_id
                    job_run.status = _CLOUD_STATUS_TO_RESULT.get(outcome.status, "FAILED")
                    for row in outcome.test_rows:
                        db.add(
                            DbtTestResult(
                                dbt_job_run_id=job_run.id,
                                unique_id=row.unique_id,
                                node_kind=row.node_kind,
                                name=row.name,
                                status=row.status,
                                execution_time=row.execution_time,
                                message=row.message,
                                relation_name=row.relation_name,
                            )
                        )
                    if outcome.raw_run_json:
                        db.add(Artifact(run_id=run.id, kind=f"dbt_cloud_run:{label}", content=outcome.raw_run_json))
                    if outcome.error:
                        run.error_message = ((run.error_message or "") + f"\n[dbt:{label}] {outcome.error}").strip()

                job_run.finished_at = datetime.now(timezone.utc)
                if job_run.status != "PASSED":
                    overall_ok = False

            else:  # ("airflow", dag_id, outcome)
                _, dag_id, outcome = item
                dag_run_row = AirflowDagRun(
                    run_id=run.id,
                    dag_id=outcome.dag_id,
                    airflow_dag_run_id=outcome.dag_run_id,
                    state=outcome.state,
                    logical_date=outcome.logical_date,
                    start_date=outcome.start_date,
                    end_date=outcome.end_date,
                )
                db.add(dag_run_row)
                db.flush()
                for t in outcome.tasks:
                    db.add(
                        AirflowTaskResult(
                            airflow_dag_run_pk=dag_run_row.id,
                            task_id=t.task_id,
                            state=t.state,
                            duration=t.duration,
                            try_number=t.try_number,
                        )
                    )
                if outcome.raw_dag_run_json:
                    db.add(Artifact(run_id=run.id, kind=f"airflow_dag_run:{dag_id}", content=outcome.raw_dag_run_json))
                if outcome.error:
                    run.error_message = ((run.error_message or "") + f"\n[airflow:{dag_id}] {outcome.error}").strip()
                if outcome.state not in ("success", "UNREACHABLE"):
                    overall_ok = False

        if not results:
            run.status = "ERROR"
            run.error_message = ((run.error_message or "") + "\nNo dbt jobs or Airflow DAGs were selected.").strip()
        else:
            run.status = "PASSED" if overall_ok else "FAILED"

        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        logger.exception("Test run %s crashed", run_id)
        run = db.get(TestRun, run_id)
        if run is not None:
            run.status = "ERROR"
            run.error_message = f"orchestrator crashed: {exc}"
            db.commit()
    finally:
        db.close()
