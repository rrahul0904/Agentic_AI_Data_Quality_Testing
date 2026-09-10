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
from .knowledge import attach_knowledge_routes


_CERTIFICATION_PATH = "/api/v1/certification/coco"
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


def _compose(application: FastAPI) -> FastAPI:
    application = _attach_certification_route(application)
    return attach_knowledge_routes(application)


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
