"""Read-only production/external assurance status API."""

from __future__ import annotations

import os
from pathlib import Path
import re

from fastapi import FastAPI

from agentic_data_platform.certification.production import (
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


def _external_evidence_from_environment() -> dict[str, object]:
    configured = os.getenv("ADE_EXTERNAL_ASSURANCE_EVIDENCE", "").strip()
    if not configured:
        return {}
    path = Path(configured).expanduser()
    if not path.is_file():
        return {}
    return dict(load_external_evidence(path))


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

    payload = build_production_certification(
        commit_sha,
        local_gate_passed=False,
        external_evidence=_external_evidence_from_environment(),
    )
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
