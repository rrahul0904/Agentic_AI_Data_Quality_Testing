from __future__ import annotations

"""Hosted ASGI entrypoint.

The existing API factory remains authoritative. This entrypoint injects cloud-aware
persistence adapters without changing the local/default application module:

- ``ADE_DATABASE_URL`` selects PostgreSQL for control-plane state;
- ``ADE_INVESTIGATION_DATABASE_URL`` selects PostgreSQL for incident/evidence state;
- ``ADE_QUALITY_DATABASE_URL`` selects PostgreSQL for quality/reconciliation state;
- absent those URLs, the existing SQLite/filesystem behavior is preserved.

The API factory currently constructs its investigation store internally and the tool
registry constructs quality stores from a database argument. To keep this prototype
slice bounded and avoid a high-risk rewrite of the large certified route/tool modules,
this hosted entrypoint injects the durable adapters at those two construction seams.
The patches are process-local to this hosted ASGI module; local/default application
startup remains unchanged.
"""

import importlib
import os

from agentic_data_platform.agents.store_factory import create_investigation_store
from agentic_data_platform.persistence.factory import create_control_plane_repository
from agentic_data_platform.quality.store_factory import create_quality_store


api_module = importlib.import_module("agentic_data_platform.api.app")
builtin_tools = importlib.import_module("agentic_data_platform.tools.builtin")
repository = create_control_plane_repository()
investigation_store = create_investigation_store()

_original_investigation_store = api_module.InvestigationStore
api_module.InvestigationStore = lambda *_args, **_kwargs: investigation_store

quality_database_url = os.getenv("ADE_QUALITY_DATABASE_URL")
if quality_database_url:
    # ``api.app`` normally returns a filesystem Path and ``builtin._quality`` normally
    # constructs SQLite directly. In hosted mode the URL must survive both seams so
    # every quality tool shares the configured durable backend instead of silently
    # creating process-local state.
    api_module._quality_database = lambda: quality_database_url
    builtin_tools.SQLiteQualityStore = create_quality_store

try:
    app = api_module.create_app(repository=repository)
finally:
    api_module.InvestigationStore = _original_investigation_store
