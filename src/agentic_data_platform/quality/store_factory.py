from __future__ import annotations

import os
from pathlib import Path

from agentic_data_platform.quality.postgres_store import PostgresQualityStore
from agentic_data_platform.quality.store import SQLiteQualityStore


def create_quality_store(configured: str | Path | None = None):
    """Create a quality evidence store for local or hosted runtime.

    Precedence:
      1. explicit value,
      2. ADE_QUALITY_DATABASE_URL,
      3. ADE_QUALITY_DATABASE,
      4. local .ade database fallback.

    Remote schemes fail closed so a hosted deployment cannot silently fall back to
    process-local SQLite when an unsupported durable backend is configured.
    """

    raw = (
        str(configured) if configured is not None else
        os.getenv("ADE_QUALITY_DATABASE_URL")
        or os.getenv("ADE_QUALITY_DATABASE")
        or str(Path.cwd() / ".ade" / "quality.db")
    )
    value = raw.strip()
    if not value:
        raise ValueError("quality persistence configuration cannot be empty")

    if value.startswith(("postgres://", "postgresql://")):
        return PostgresQualityStore(value)
    if "://" in value:
        scheme = value.split("://", 1)[0]
        raise ValueError(f"unsupported quality persistence scheme: {scheme}")
    return SQLiteQualityStore(value)


def quality_backend_name(store: object) -> str:
    if isinstance(store, PostgresQualityStore):
        return "postgresql"
    if isinstance(store, SQLiteQualityStore):
        return "sqlite"
    return store.__class__.__name__
