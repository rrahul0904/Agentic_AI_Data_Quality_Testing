from __future__ import annotations

"""Hosted ASGI entrypoint.

This module keeps the existing API application factory authoritative while selecting
its control-plane persistence through the cloud-aware repository factory. Local and
single-node deployments still resolve to SQLite; setting ``ADE_DATABASE_URL`` to a
PostgreSQL DSN switches the served control plane to PostgreSQL.

Investigation and quality stores remain on their existing adapters for this bounded
slice and are deliberately not represented as cloud-native yet.
"""

from agentic_data_platform.api.app import create_app
from agentic_data_platform.persistence.factory import create_control_plane_repository


repository = create_control_plane_repository()
app = create_app(repository=repository)
