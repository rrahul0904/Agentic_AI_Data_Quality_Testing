from __future__ import annotations

"""Hosted ASGI entrypoint.

The existing API factory remains authoritative. This entrypoint injects cloud-aware
persistence adapters without changing the local/default application module:

- ``ADE_DATABASE_URL`` selects PostgreSQL for control-plane state;
- ``ADE_INVESTIGATION_DATABASE_URL`` selects PostgreSQL for incident/evidence state;
- absent those URLs, the existing SQLite/filesystem behavior is preserved.

The API factory currently constructs its investigation store internally. To keep this
prototype slice bounded and avoid a high-risk rewrite of the large certified route
module, this entrypoint temporarily replaces that constructor while ``create_app``
builds the hosted application, then restores it. The resulting FastAPI app owns the
selected durable store through the SupervisorAgent closure.
"""

import importlib

from agentic_data_platform.agents.store_factory import create_investigation_store
from agentic_data_platform.persistence.factory import create_control_plane_repository


api_module = importlib.import_module("agentic_data_platform.api.app")
repository = create_control_plane_repository()
investigation_store = create_investigation_store()

_original_investigation_store = api_module.InvestigationStore
api_module.InvestigationStore = lambda *_args, **_kwargs: investigation_store
try:
    app = api_module.create_app(repository=repository)
finally:
    api_module.InvestigationStore = _original_investigation_store
