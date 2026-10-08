from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from agentic_data_platform.persistence.postgres import PostgresControlPlaneRepository
from agentic_data_platform.persistence.repositories import ControlPlaneRepository
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository


def _sqlite_path(value: str) -> str:
    if value == ":memory:":
        return value
    if not value.startswith("sqlite://"):
        return value

    parsed = urlparse(value)
    if parsed.scheme != "sqlite":
        raise ValueError(f"unsupported sqlite URL: {value}")

    if parsed.netloc not in {"", "localhost"}:
        raise ValueError("sqlite URLs must reference a local filesystem path")

    path = unquote(parsed.path)
    if path in {"/:memory:", ":memory:"}:
        return ":memory:"
    if not path:
        raise ValueError("sqlite URL must include a database path")

    # sqlite:///relative.db is represented as /relative.db by urlparse. Keep the
    # conventional SQLAlchemy-style absolute path for sqlite:////tmp/a.db and
    # trim one leading slash for the three-slash relative form.
    if value.startswith("sqlite:////"):
        return path
    return path.lstrip("/")


def create_control_plane_repository(configured: str | None = None) -> ControlPlaneRepository:
    """Create the control-plane repository from an explicit URL/path or env.

    Precedence:
      1. explicit ``configured`` value,
      2. ``ADE_DATABASE_URL`` for hosted deployments,
      3. ``ADE_DATABASE_PATH`` for local/demo deployments,
      4. ``ade.db`` local fallback.

    Only SQLite and PostgreSQL are accepted. Unknown URL schemes fail closed.
    """

    value = (
        configured
        or os.getenv("ADE_DATABASE_URL")
        or os.getenv("ADE_DATABASE_PATH")
        or "ade.db"
    ).strip()
    if not value:
        raise ValueError("control-plane persistence configuration cannot be empty")

    if value.startswith(("postgres://", "postgresql://")):
        return PostgresControlPlaneRepository(value)

    if value.startswith("sqlite://") or value == ":memory:" or "://" not in value:
        path = _sqlite_path(value)
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        return SQLiteControlPlaneRepository(path)

    scheme = urlparse(value).scheme or "unknown"
    raise ValueError(f"unsupported control-plane persistence scheme: {scheme}")


def persistence_backend_name(repository: ControlPlaneRepository) -> str:
    if isinstance(repository, PostgresControlPlaneRepository):
        return "postgresql"
    if isinstance(repository, SQLiteControlPlaneRepository):
        return "sqlite"
    return repository.__class__.__name__
