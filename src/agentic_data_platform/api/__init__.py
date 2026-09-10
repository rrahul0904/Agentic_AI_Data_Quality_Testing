"""Public FastAPI assembly for the Agentic Data Engineering OS.

The large legacy application stays stable while independently testable routers are
composed here.  The compatibility assignment keeps direct imports from
``agentic_data_platform.api.app`` on the same factory contract.
"""

from __future__ import annotations

from . import app as _legacy_app
from .certification import router as certification_router


_legacy_create_app = _legacy_app.create_app


def create_app(repository=None):
    application = _legacy_create_app(repository)
    application.include_router(certification_router)
    return application


# Preserve the long-standing direct-module import/API-server surfaces without
# modifying the restored monolithic app.py again.
_legacy_app.create_app = create_app
_legacy_app.app.include_router(certification_router)

__all__ = ["create_app"]
