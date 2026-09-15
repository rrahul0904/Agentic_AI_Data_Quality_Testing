"""Public FastAPI assembly for the Agentic Data Engineering OS.

The legacy monolithic factory remains intact while small capability routers are attached
through idempotent composition layers. The wrapper captures its underlying factory by
value so package/module reloads cannot turn compatibility composition into self-reference
or silently drop routes.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import app as _legacy_app
from .certification import coco_status
from .competitive import attach_competitive_routes
from .health import HEALTH_PATH, attach_health_route
from .knowledge import attach_knowledge_routes


_CERTIFICATION_PATH = "/api/v1/certification/coco"
_COMPOSED_PATHS = {
    HEALTH_PATH,
    _CERTIFICATION_PATH,
    "/api/v1/agent/query",
    "/api/v1/knowledge/status",
    "/api/v1/knowledge/search",
    "/api/v1/knowledge/index-project",
    "/api/v1/knowledge/ingest-text",
    "/api/v1/knowledge/upload",
    "/api/v1/competitive/status",
    "/api/v1/retrieval/search",
    "/api/v1/search/index",
    "/api/v1/search/query",
    "/api/v1/search/multi-query",
    "/api/v1/search/stats",
    "/api/v1/search/delete-source",
    "/api/v1/document/process",
    "/api/v1/compute/plan",
    "/api/v1/document/snowflake-plan",
}
_base_create_app = _legacy_app.create_app


def _has_certification_route(application: FastAPI) -> bool:
    return any(
        getattr(route, "path", None) == _CERTIFICATION_PATH
        and "GET" in (getattr(route, "methods", set()) or set())
        for route in application.routes
    )


def _attach_certification_route(application: FastAPI) -> FastAPI:
    if not _has_certification_route(application):
        application.add_api_route(
            _CERTIFICATION_PATH,
            coco_status,
            methods=["GET"],
            tags=["certification"],
            name="coco_certification_status",
        )
    return application


def _prioritize_composed_routes(application: FastAPI) -> FastAPI:
    """Place exact composed routes ahead of the generic `/api/v1/{...}` dispatcher."""

    composed = []
    remaining = []
    for route in application.router.routes:
        if getattr(route, "path", None) in _COMPOSED_PATHS:
            composed.append(route)
        else:
            remaining.append(route)
    insertion = next(
        (
            index
            for index, route in enumerate(remaining)
            if str(getattr(route, "path", "")).startswith("/api/v1/{")
        ),
        len(remaining),
    )
    application.router.routes = remaining[:insertion] + composed + remaining[insertion:]
    return application


def _compose(application: FastAPI) -> FastAPI:
    application = attach_health_route(application)
    application = _attach_certification_route(application)
    application = attach_knowledge_routes(application)
    application = attach_competitive_routes(application)
    return _prioritize_composed_routes(application)


def create_app(repository=None, *, _factory=_base_create_app):
    """Create the canonical ADE API with capability routing attached exactly once."""

    application = _factory(repository)
    if not isinstance(application, FastAPI):
        raise TypeError("legacy create_app() did not return a FastAPI application")
    return _compose(application)


# Preserve the long-standing direct-module factory and ASGI surfaces. Capturing
# `_factory` as a default argument above makes package reloads safe: older wrappers
# retain their original underlying factory instead of following a mutable module
# global back to themselves. Do not assign a package-level `app` object here because
# that would shadow the `agentic_data_platform.api.app` submodule on reload.
_legacy_app.create_app = create_app
_legacy_app.app = _compose(_legacy_app.app)

__all__ = ["create_app"]
