import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import DbtJob, DbtProject
from ..schemas import (
    DbtJobCreate,
    DbtJobOut,
    DbtProjectCreate,
    DbtProjectDetail,
    DbtProjectOut,
    LineageOut,
)
from ..services import provisioning
from ..services.lineage import refresh_dbt_lineage

logger = logging.getLogger("ade.dbt_projects")
router = APIRouter(prefix="/api/dbt-projects", tags=["dbt-projects"])


async def _provision(project_id: str, payload: DbtProjectCreate) -> None:
    db: Session = SessionLocal()
    try:
        project = db.get(DbtProject, project_id)
        if project is None:
            return
        try:
            if payload.execution_mode == "local":
                result = await asyncio.to_thread(
                    provisioning.provision_dbt_local_project, project_id, payload.name, payload.adapter
                )
                project.venv_path = result["venv_path"]
                project.project_dir = result["project_dir"]
                project.profiles_dir = result["profiles_dir"]
                project.adapter = result["adapter"]

                dbt_bin = f"{result['venv_path']}/bin/dbt"
                lineage = await asyncio.to_thread(
                    refresh_dbt_lineage, dbt_bin, result["project_dir"], result["profiles_dir"], project.dbt_target
                )
                project.lineage_json = json.dumps(lineage)
                from datetime import datetime, timezone

                project.lineage_refreshed_at = datetime.now(timezone.utc)
            else:
                await asyncio.to_thread(
                    provisioning.validate_dbt_cloud_credentials,
                    payload.dbt_cloud_host or "cloud.getdbt.com",
                    payload.dbt_cloud_account_id,
                    payload.dbt_cloud_api_token,
                )
            project.status = "READY"
        except Exception as exc:  # noqa: BLE001 - surface any provisioning failure to the UI
            logger.exception("Provisioning dbt project %s failed", project_id)
            project.status = "ERROR"
            project.error_message = str(exc)
        db.commit()
    finally:
        db.close()


@router.post("", response_model=DbtProjectOut, status_code=201)
async def create_dbt_project(payload: DbtProjectCreate, db: Session = Depends(get_db)):
    if payload.execution_mode not in ("local", "cloud"):
        raise HTTPException(422, "execution_mode must be 'local' or 'cloud'")
    if payload.execution_mode == "local" and not payload.adapter:
        raise HTTPException(422, "adapter is required for execution_mode='local'")
    if payload.execution_mode == "cloud" and not (
        payload.dbt_cloud_account_id and payload.dbt_cloud_api_token
    ):
        raise HTTPException(422, "dbt_cloud_account_id and dbt_cloud_api_token are required for execution_mode='cloud'")

    project = DbtProject(
        name=payload.name,
        execution_mode=payload.execution_mode,
        adapter=payload.adapter,
        dbt_cloud_host=payload.dbt_cloud_host or "cloud.getdbt.com",
        dbt_cloud_account_id=payload.dbt_cloud_account_id,
        dbt_cloud_project_id=payload.dbt_cloud_project_id,
        dbt_cloud_api_token=payload.dbt_cloud_api_token,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    asyncio.create_task(_provision(project.id, payload))
    return project


@router.get("", response_model=list[DbtProjectOut])
def list_dbt_projects(db: Session = Depends(get_db)):
    return db.scalars(select(DbtProject).order_by(DbtProject.created_at.desc())).all()


@router.get("/{project_id}", response_model=DbtProjectDetail)
def get_dbt_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(DbtProject, project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")
    return project


@router.post("/{project_id}/jobs", response_model=DbtJobOut, status_code=201)
def create_dbt_job(project_id: str, payload: DbtJobCreate, db: Session = Depends(get_db)):
    project = db.get(DbtProject, project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")
    if project.execution_mode != "local":
        raise HTTPException(422, "local-select jobs can only be added to execution_mode='local' projects")
    job = DbtJob(dbt_project_id=project_id, name=payload.name, kind="local_select", select_str=payload.select_str)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/{project_id}/sync-cloud-jobs", response_model=list[DbtJobOut])
def sync_cloud_jobs(project_id: str, db: Session = Depends(get_db)):
    project = db.get(DbtProject, project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")
    if project.execution_mode != "cloud":
        raise HTTPException(422, "sync-cloud-jobs is only for execution_mode='cloud' projects")

    from ..services.dbt_cloud_client import DbtCloudApiError, DbtCloudClient

    client = DbtCloudClient(
        host=project.dbt_cloud_host, account_id=project.dbt_cloud_account_id, api_token=project.dbt_cloud_api_token
    )
    try:
        cloud_jobs = client.list_jobs(project.dbt_cloud_project_id)
    except DbtCloudApiError as exc:
        raise HTTPException(502, f"dbt Cloud API error: {exc}") from exc

    existing = {j.dbt_cloud_job_id: j for j in project.jobs if j.kind == "cloud_job"}
    for cj in cloud_jobs:
        cj_id = str(cj["id"])
        if cj_id in existing:
            existing[cj_id].name = cj.get("name", existing[cj_id].name)
        else:
            db.add(
                DbtJob(
                    dbt_project_id=project_id,
                    name=cj.get("name", cj_id),
                    kind="cloud_job",
                    dbt_cloud_job_id=cj_id,
                    schedule_description=str(cj.get("schedule", {}).get("cron")) if cj.get("schedule") else None,
                )
            )
    db.commit()
    db.refresh(project)
    return project.jobs


@router.get("/{project_id}/lineage", response_model=LineageOut)
def get_dbt_lineage(project_id: str, db: Session = Depends(get_db)):
    project = db.get(DbtProject, project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")
    if not project.lineage_json:
        return LineageOut()
    return LineageOut(**json.loads(project.lineage_json))


@router.post("/{project_id}/lineage/refresh", response_model=LineageOut)
async def refresh_lineage(project_id: str, db: Session = Depends(get_db)):
    project = db.get(DbtProject, project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")
    if project.execution_mode != "local" or project.status != "READY":
        raise HTTPException(422, "lineage refresh needs a READY, execution_mode='local' project")

    dbt_bin = f"{project.venv_path}/bin/dbt"
    lineage = await asyncio.to_thread(
        refresh_dbt_lineage, dbt_bin, project.project_dir, project.profiles_dir, project.dbt_target
    )
    project.lineage_json = json.dumps(lineage)
    from datetime import datetime, timezone

    project.lineage_refreshed_at = datetime.now(timezone.utc)
    db.commit()
    return LineageOut(**lineage)
