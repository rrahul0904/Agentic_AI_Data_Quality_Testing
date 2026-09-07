from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import airflow_projects, dbt_projects, investigation, quality, runs

app = FastAPI(title="ADE Test Control Tower", version="0.6.0-horizon-a")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.6.0-horizon-a"}


app.include_router(dbt_projects.router)
app.include_router(airflow_projects.router)
app.include_router(runs.router)
app.include_router(quality.router)
app.include_router(investigation.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
