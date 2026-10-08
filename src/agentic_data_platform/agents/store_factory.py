from __future__ import annotations

import os
from pathlib import Path

from agentic_data_platform.agents.postgres_store import PostgresInvestigationStore
from agentic_data_platform.agents.store import InvestigationStore


def create_investigation_store(configured: str | None = None):
    """Create the investigation store for local or hosted runtime.

    Precedence:
      1. explicit value,
      2. ADE_INVESTIGATION_DATABASE_URL,
      3. ADE_INVESTIGATION_DATABASE,
      4. local .ade database fallback.
    """

    value = (
        configured
        or os.getenv("ADE_INVESTIGATION_DATABASE_URL")
        or os.getenv("ADE_INVESTIGATION_DATABASE")
        or str(Path.cwd() / ".ade" / "agentic-investigations.db")
    ).strip()
    if not value:
        raise ValueError("investigation persistence configuration cannot be empty")

    if value.startswith(("postgres://", "postgresql://")):
        return PostgresInvestigationStore(value)
    if "://" in value:
        scheme = value.split("://", 1)[0]
        raise ValueError(f"unsupported investigation persistence scheme: {scheme}")
    return InvestigationStore(value)


def investigation_backend_name(store: object) -> str:
    if isinstance(store, PostgresInvestigationStore):
        return "postgresql"
    if isinstance(store, InvestigationStore):
        return "sqlite"
    return store.__class__.__name__
