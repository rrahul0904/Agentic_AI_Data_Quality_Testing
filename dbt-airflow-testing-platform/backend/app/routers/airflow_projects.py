import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..models import AirflowDagRef, AirflowProject
from ..schemas import AirflowProjectCreate, AirflowProjectDetail, AirflowProjectOut, LineageOut
from ..services import provisioning
from ..services.airflow_client import AirflowClient
from ..services.lineage import refresh_airflow_dag_lineage

logger = logging.getLogger("ade.airflow_projects")
router = APIRouter(prefix="/api/airflow-projects", tags=["airflow-projects"])


def _client_for(project: AirflowProject) -> AirflowClient:
    return AirflowClient(
        base_url=project.base_url,
        username=project.admin_username,
        password=project.admin_password,
        timeout_seconds=settings.airflow_request_timeout_seconds,
    )


async def _provision(project_id: str) -> None:
    db: Session = SessionLocal()
    try:
        project = db.get(AirflowProject, project_id)
        if project is None:
            return
        try:
            result = await asyncio.to_thread(provisioning.provision_airflow_project, project_id)
            for key, value in result.items():
                setattr(project, key, value)
            project.status = "READY"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Provisioning airflow project %s failed", project_id)
            project.status = "ERROR"
            project.error_message = str(exc)
        db.commit()
    finally:
        db.close()


def _with_running_flag(project: AirflowProject) -> AirflowProjectOut:
    out = AirflowProjectOut.model_validate(project)
    out.is_running = project.status == "READY" and provisioning.is_process_alive(project.webserver_pid)
    return out


@router.post("", response_model=AirflowProjectOut, status_code=201)
async def create_airflow_project(payload: AirflowProjectCreate, db: Session = Depends(get_db)):
    project = AirflowProject(name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)

    asyncio.create_task(_provision(project.id))
    return _with_running_flag(project)


@router.get("", response_model=list[AirflowProjectOut])
def list_airflow_projects(db: Session = Depends(get_db)):
    projects = db.scalars(select(AirflowProject).order_by(AirflowProject.created_at.desc())).all()
    return [_with_running_flag(p) for p in projects]


@router.get("/{project_id}", response_model=AirflowProjectDetail)
def get_airflow_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(AirflowProject, project_id)
    if project is None:
        raise HTTPException(404, "airflow project not found")
    out = AirflowProjectDetail.model_validate(project)
    out.is_running = project.status == "READY" and provisioning.is_process_alive(project.webserver_pid)
    return out


@router.post("/{project_id}/stop", response_model=AirflowProjectOut)
def stop_airflow_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(AirflowProject, project_id)
    if project is None:
        raise HTTPException(404, "airflow project not found")
    provisioning.stop_airflow_project(project)
    project.status = "STOPPED"
    db.commit()
    return _with_running_flag(project)


@router.post("/{project_id}/start", response_model=AirflowProjectOut)
async def start_airflow_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(AirflowProject, project_id)
    if project is None:
        raise HTTPException(404, "airflow project not found")
    try:
        result = await asyncio.to_thread(provisioning.start_airflow_project, project)
        for key, value in result.items():
            setattr(project, key, value)
        project.status = "READY"
        project.error_message = None
    except Exception as exc:  # noqa: BLE001
        project.status = "ERROR"
        project.error_message = str(exc)
    db.commit()
    return _with_running_flag(project)


class DagUpload(BaseModel):
    filename: str
    content: str


@router.post("/{project_id}/dags", status_code=201)
def upload_dag(project_id: str, payload: DagUpload, db: Session = Depends(get_db)):
    project = db.get(AirflowProject, project_id)
    if project is None:
        raise HTTPException(404, "airflow project not found")
    if project.status != "READY":
        raise HTTPException(422, "airflow project is not READY yet")

    filename = Path(payload.filename).name
    if not filename.endswith(".py"):
        filename += ".py"
    dags_dir = Path(project.airflow_home) / "dags"
    (dags_dir / filename).write_text(payload.content)
    return {"written_to": str(dags_dir / filename), "note": "New DAG files are discovered every ~10s; call /dags/sync a few seconds after uploading."}


@router.post("/{project_id}/dags/sync", response_model=list[dict])
def sync_dags(project_id: str, db: Session = Depends(get_db)):
    project = db.get(AirflowProject, project_id)
    if project is None:
        raise HTTPException(404, "airflow project not found")
    if project.status != "READY":
        raise HTTPException(422, "airflow project is not READY yet")

    client = _client_for(project)
    try:
        dags = client.list_dags()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"could not reach this project's Airflow instance: {exc}") from exc

    existing = {d.dag_id: d for d in project.dags}
    for dag in dags:
        dag_id = dag["dag_id"]
        try:
            lineage = refresh_airflow_dag_lineage(client, dag_id)
            lineage_json = json.dumps(lineage)
        except Exception:  # noqa: BLE001
            lineage_json = None

        if dag_id in existing:
            ref = existing[dag_id]
        else:
            ref = AirflowDagRef(airflow_project_id=project_id, dag_id=dag_id)
            db.add(ref)
        ref.schedule_interval = str(dag.get("schedule_interval")) if dag.get("schedule_interval") else None
        ref.is_paused = bool(dag.get("is_paused"))
        ref.tags = [t.get("name") for t in dag.get("tags", [])]
        if lineage_json:
            ref.lineage_json = lineage_json

    db.commit()
    db.refresh(project)
    return [
        {
            "dag_id": d.dag_id,
            "schedule_interval": d.schedule_interval,
            "is_paused": d.is_paused,
            "tags": d.tags,
        }
        for d in project.dags
    ]


@router.get("/{project_id}/dags/{dag_id}/lineage", response_model=LineageOut)
def get_dag_lineage(project_id: str, dag_id: str, db: Session = Depends(get_db)):
    ref = db.scalar(
        select(AirflowDagRef).where(AirflowDagRef.airflow_project_id == project_id, AirflowDagRef.dag_id == dag_id)
    )
    if ref is None:
        raise HTTPException(404, "dag not found in this project; call /dags/sync first")
    if not ref.lineage_json:
        return LineageOut()
    return LineageOut(**json.loads(ref.lineage_json))
