"""Deployment health surface for the ADE control plane."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI


HEALTH_PATH = "/healthz"


def attach_health_route(application: FastAPI) -> FastAPI:
    if any(
        getattr(route, "path", None) == HEALTH_PATH
        and "GET" in (getattr(route, "methods", set()) or set())
        for route in application.routes
    ):
        return application

    @application.get(HEALTH_PATH, tags=["platform"], include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {
            "status": "PASS",
            "service": "ade-api",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return application


__all__ = ["HEALTH_PATH", "attach_health_route"]
