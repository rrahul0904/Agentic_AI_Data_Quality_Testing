"""Public FastAPI assembly for the Agentic Data Engineering OS.

The legacy monolithic factory remains intact while certification routing is attached
through a small, idempotent composition layer.  The wrapper captures its underlying
factory by value so package/module reloads cannot turn the compatibility patch into
self-reference or silently drop the certification route.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import app as _legacy_app
from .certification import coco_status


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


def create_app(repository=None, *, _factory=_base_create_app):
    """Create the canonical ADE API with certification routing attached exactly once."""

    application = _factory(repository)
    if not isinstance(application, FastAPI):
        raise TypeError("legacy create_app() did not return a FastAPI application")
    return _attach_certification_route(application)


# Preserve both long-standing import surfaces.  Capturing `_factory` as a default
# argument above makes this safe even if the package is reloaded during a test or
# embedding lifecycle: an older wrapper still points to the original factory rather
# than a mutable module global that can later point back to itself.
_legacy_app.create_app = create_app
_legacy_app.app = _attach_certification_route(_legacy_app.app)
app = _legacy_app.app

__all__ = ["app", "create_app"]
