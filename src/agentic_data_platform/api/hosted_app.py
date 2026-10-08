from __future__ import annotations

"""Hosted ASGI entrypoint.

The existing API factory remains authoritative. This entrypoint injects cloud-aware
persistence, project-source, and artifact adapters without changing local/default startup:

- ``ADE_DATABASE_URL`` selects PostgreSQL for control-plane state;
- ``ADE_INVESTIGATION_DATABASE_URL`` selects PostgreSQL for incident/evidence state;
- ``ADE_QUALITY_DATABASE_URL`` selects PostgreSQL for quality/reconciliation state;
- ``ADE_PROJECT_SOURCE_MODE=git`` materializes an allowlisted HTTPS Git project into
  the managed workspace and points the existing API/tool seams at that exact checkout;
- ``ADE_ARTIFACT_STORE_MODE`` selects verified filesystem or S3-compatible artifacts;
- filesystem/embedded-demo behavior remains available for local and demo use.
"""

import importlib
import os
from pathlib import Path

from agentic_data_platform.agents.store_factory import create_investigation_store
from agentic_data_platform.artifacts.factory import create_artifact_store
from agentic_data_platform.persistence.factory import create_control_plane_repository
from agentic_data_platform.projects.sources import resolve_hosted_project
from agentic_data_platform.quality.store_factory import create_quality_store


program_root = Path(__file__).resolve().parents[3]
project = resolve_hosted_project(default_project=program_root / "hospitality-snowflake-data-platform")
os.environ["ADE_PROJECT_ROOT"] = str(project.root)
artifact_store = create_artifact_store()

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

# Keep the adapter provider-neutral for API/agent integrations. A Git materialization
# also gets an immutable source receipt mirrored into artifact storage so hosted runs
# can prove exactly which project revision was analyzed even after worker cleanup.
app.state.artifact_store = artifact_store
app.state.project_source_artifact_receipt = None
source_receipt = project.root / ".ade" / "project-source.json"
if project.mode == "git" and project.source_ref and source_receipt.is_file():
    app.state.project_source_artifact_receipt = artifact_store.put_bytes(
        f"project-sources/{project.source_ref}/receipt.json",
        source_receipt.read_bytes(),
        content_type="application/json",
    )
