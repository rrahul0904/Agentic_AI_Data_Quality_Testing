"""Read-only production/external assurance status API."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

from fastapi import FastAPI

from agentic_data_platform.certification.production import (
    AssuranceStatus,
    build_production_certification,
    load_external_evidence,
)


PRODUCTION_CERTIFICATION_PATH = "/api/v1/certification/production"
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _has_route(application: FastAPI) -> bool:
    return any(
        getattr(route, "path", None) == PRODUCTION_CERTIFICATION_PATH
        and "GET" in (getattr(route, "methods", set()) or set())
        for route in application.routes
    )


def _external_evidence_from_environment() -> tuple[dict[str, object], bool]:
    configured = os.getenv("ADE_EXTERNAL_ASSURANCE_EVIDENCE", "").strip()
    if not configured:
        return {}, False
    path = Path(configured).expanduser()
    if not path.is_file():
        return {}, False
    try:
        return dict(load_external_evidence(path)), False
    except (json.JSONDecodeError, OSError, ValueError):
        return {}, True


def _block_external_records(payload: dict[str, object], commit_sha: str) -> None:
    records = payload.get("records")
    if not isinstance(records, list):
        return
    for record in records:
        if not isinstance(record, dict) or record.get("track") != "EXTERNAL_ASSURANCE":
            continue
        record["status"] = AssuranceStatus.BLOCKED_EXTERNAL.value
        record["evidence"] = {
            "commit_sha": commit_sha,
            "reason": "configured external evidence could not be loaded",
        }
    counts: dict[str, int] = {}
    for record in records:
        if isinstance(record, dict):
            status = str(record.get("status", ""))
            counts[status] = counts.get(status, 0) + 1
    payload["counts"] = counts


def production_certification_status() -> dict[str, object]:
    """Report assurance state; runtime presence alone never certifies the current build."""

    commit_sha = os.getenv("ADE_COMMIT_SHA", "").strip()
    if not _SHA.fullmatch(commit_sha):
        return {
            "schema_version": 1,
            "status": "UNBOUND_RUNTIME",
            "commit_sha": None,
            "local_gate_passed": False,
            "superior": False,
            "records": [],
            "truthfulness": {
                "reason": "set ADE_COMMIT_SHA to an exact 40-character build SHA to bind this runtime",
                "runtime_endpoint_is_not_a_certification_gate": True,
                "external_status_never_inferred": True,
            },
        }

    external_evidence, external_load_failed = _external_evidence_from_environment()
    payload = build_production_certification(
        commit_sha,
        local_gate_passed=False,
        external_evidence=external_evidence,
    )
    if external_load_failed:
        _block_external_records(payload, commit_sha)
        payload["status"] = AssuranceStatus.BLOCKED_EXTERNAL.value
        truthfulness = payload.get("truthfulness")
        if isinstance(truthfulness, dict):
            truthfulness["external_evidence_load_failed"] = True
    else:
        payload["status"] = "REPORT_ONLY"
    return payload


def attach_production_certification_routes(application: FastAPI) -> FastAPI:
    if _has_route(application):
        return application
    application.add_api_route(
        PRODUCTION_CERTIFICATION_PATH,
        production_certification_status,
        methods=["GET"],
        tags=["certification"],
        name="production_certification_status",
    )
    return application
