"""Self-contained certification routes for the ADE operator API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from agentic_data_platform.certification import coco_certification_status


router = APIRouter(prefix="/api/v1/certification", tags=["certification"])


def _program_root() -> Path:
    return Path(__file__).resolve().parents[3]


@router.get("/coco")
def coco_status() -> dict[str, object]:
    """Expose truthful CoCo certification state from repository evidence."""

    return coco_certification_status(_program_root())
