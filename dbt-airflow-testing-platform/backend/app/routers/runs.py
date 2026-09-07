import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import TestRun
from ..schemas import RunCreateRequest, TestRunDetail, TestRunSummary
from ..services.orchestrator import execute_test_run

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=TestRunSummary, status_code=201)
async def create_run(payload: RunCreateRequest, db: Session = Depends(get_db)):
    if not payload.dbt_project_id and not payload.airflow_project_id:
        raise HTTPException(422, "at least one of dbt_project_id / airflow_project_id is required")

    run = TestRun(
        dbt_project_id=payload.dbt_project_id,
        dbt_job_ids=payload.dbt_job_ids or None,
        dbt_adhoc_select=payload.dbt_select,
        airflow_project_id=payload.airflow_project_id,
        airflow_dag_ids=payload.airflow_dag_ids or None,
        triggered_by=payload.triggered_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Fire-and-forget the async orchestration; the run row is the handle the
    # UI polls, so we don't need to hold the HTTP request open.
    asyncio.create_task(execute_test_run(run.id))

    return run


@router.get("", response_model=list[TestRunSummary])
def list_runs(db: Session = Depends(get_db)):
    runs = db.scalars(select(TestRun).order_by(TestRun.created_at.desc()).limit(50)).all()
    return runs


@router.get("/{run_id}", response_model=TestRunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
