"""Local-first AI teammate manager compatible with the Datamate lifecycle."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from agentic_data_platform.mcp import McpCatalog, McpConfigStore
from agentic_data_platform.models import new_id, utc_now


def slugify(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return value[:64] or "teammate"


class TeammateStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS teammates (
              teammate_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT,
              integration_ids_json TEXT NOT NULL,
              memory_enabled INTEGER NOT NULL DEFAULT 1,
              privacy TEXT NOT NULL DEFAULT 'private',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(teammates)").fetchall()
        }
        migrations = {
            "role": "TEXT NOT NULL DEFAULT 'specialist'",
            "allowed_tools_json": "TEXT NOT NULL DEFAULT '[]'",
            "budgets_json": "TEXT NOT NULL DEFAULT '{}'",
            "verification_json": "TEXT NOT NULL DEFAULT '[]'",
            "model": "TEXT NOT NULL DEFAULT 'inherit'",
            "system_prompt": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in migrations.items():
            if column not in columns:
                self.connection.execute(f"ALTER TABLE teammates ADD COLUMN {column} {ddl}")
        self.connection.commit()

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["integration_ids"] = json.loads(
            value.pop("integration_ids_json") or "[]"
        )
        value["memory_enabled"] = bool(value["memory_enabled"])
        value["allowed_tools"] = json.loads(value.pop("allowed_tools_json", "[]") or "[]")
        value["budgets"] = json.loads(value.pop("budgets_json", "{}") or "{}")
        value["verification"] = json.loads(value.pop("verification_json", "[]") or "[]")
        return value

    def list(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM teammates ORDER BY name, teammate_id"
        ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, teammate_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM teammates WHERE teammate_id=?",
            (teammate_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"teammate not found: {teammate_id}")
        return self._row(row)

    def create(
        self,
        name: str,
        *,
        description: str | None = None,
        integration_ids: Iterable[str] = (),
        memory_enabled: bool = True,
        privacy: str = "private",
        role: str = "specialist",
        allowed_tools: Iterable[str] = (),
        budgets: Mapping[str, Any] | None = None,
        verification: Iterable[Mapping[str, Any] | str] = (),
        model: str = "inherit",
        system_prompt: str = "",
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("teammate name is required")
        if privacy not in {"private", "public"}:
            raise ValueError("privacy must be private or public")
        teammate_id = new_id("teammate")
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO teammates(
              teammate_id,name,description,integration_ids_json,memory_enabled,
              privacy,created_at,updated_at,role,allowed_tools_json,budgets_json,
              verification_json,model,system_prompt
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                teammate_id,
                name.strip(),
                description,
                json.dumps(sorted(set(str(item) for item in integration_ids))),
                int(memory_enabled),
                privacy,
                now,
                now,
                str(role).strip() or "specialist",
                json.dumps(sorted(set(str(item) for item in allowed_tools))),
                json.dumps(dict(budgets or {}), sort_keys=True, default=str),
                json.dumps(list(verification), sort_keys=True, default=str),
                str(model or "inherit"),
                str(system_prompt or ""),
            ),
        )
        self.connection.commit()
        return self.get(teammate_id)

    def edit(
        self,
        teammate_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        integration_ids: Iterable[str] | None = None,
        memory_enabled: bool | None = None,
        privacy: str | None = None,
        role: str | None = None,
        allowed_tools: Iterable[str] | None = None,
        budgets: Mapping[str, Any] | None = None,
        verification: Iterable[Mapping[str, Any] | str] | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        current = self.get(teammate_id)
        if privacy is not None and privacy not in {"private", "public"}:
            raise ValueError("privacy must be private or public")
        self.connection.execute(
            """
            UPDATE teammates SET
              name=?, description=?, integration_ids_json=?, memory_enabled=?,
              privacy=?, role=?, allowed_tools_json=?, budgets_json=?,
              verification_json=?, model=?, system_prompt=?, updated_at=?
            WHERE teammate_id=?
            """,
            (
                name.strip() if name is not None else current["name"],
                description if description is not None else current["description"],
                json.dumps(
                    sorted(set(str(item) for item in integration_ids))
                    if integration_ids is not None
                    else current["integration_ids"]
                ),
                int(memory_enabled if memory_enabled is not None else current["memory_enabled"]),
                privacy if privacy is not None else current["privacy"],
                str(role).strip() if role is not None else current["role"],
                json.dumps(
                    sorted(set(str(item) for item in allowed_tools))
                    if allowed_tools is not None
                    else current["allowed_tools"]
                ),
                json.dumps(
                    dict(budgets) if budgets is not None else current["budgets"],
                    sort_keys=True,
                    default=str,
                ),
                json.dumps(
                    list(verification) if verification is not None else current["verification"],
                    sort_keys=True,
                    default=str,
                ),
                str(model) if model is not None else current["model"],
                str(system_prompt) if system_prompt is not None else current["system_prompt"],
                utc_now(),
                teammate_id,
            ),
        )
        self.connection.commit()
        return self.get(teammate_id)

    def delete(self, teammate_id: str) -> dict[str, Any]:
        current = self.get(teammate_id)
        cursor = self.connection.execute(
            "DELETE FROM teammates WHERE teammate_id=?",
            (teammate_id,),
        )
        self.connection.commit()
        return {
            "status": "PASS",
            "deleted": cursor.rowcount == 1,
            "teammate": current,
        }


class TeammateManager:
    def __init__(
        self,
        project_root: str | Path,
        *,
        database: str | Path | None = None,
        global_root: str | Path | None = None,
        catalog: McpCatalog | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.store = TeammateStore(
            database or self.project_root / ".ade" / "teammates.db"
        )
        self.global_root = (
            Path(global_root).expanduser().resolve()
            if global_root
            else Path.home() / ".config" / "agentic-data-platform"
        )
        self.catalog = catalog or McpCatalog.builtin()

    def config_path(self, scope: str) -> Path:
        if scope not in {"project", "global"}:
            raise ValueError("scope must be project or global")
        if scope == "global":
            return self.global_root / "agentic-data-platform.json"
        return self.project_root / ".altimate-code" / "altimate-code.json"

    def list_integrations(self) -> dict[str, Any]:
        entries = self.catalog.list()
        configured = McpConfigStore.load(self.config_path("project"))
        return {
            "status": "PASS",
            "integrations": [
                {
                    "id": item["name"],
                    "name": item["name"],
                    "description": item["description"],
                    "source": item["source"],
                }
                for item in entries
            ],
            "configured_servers": sorted(configured),
            "count": len(entries),
        }

    def _validate_integrations(self, integration_ids: Iterable[str]) -> list[str]:
        available = {item["name"] for item in self.catalog.list()}
        values = sorted(set(str(item) for item in integration_ids))
        missing = [item for item in values if item not in available]
        if missing:
            raise KeyError(
                "unknown teammate integrations: " + ", ".join(missing)
            )
        return values

    def create(self, **kwargs: Any) -> dict[str, Any]:
        integrations = self._validate_integrations(
            kwargs.pop("integration_ids", ())
        )
        return self.store.create(
            integration_ids=integrations,
            **kwargs,
        )

    def edit(self, teammate_id: str, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("integration_ids") is not None:
            kwargs["integration_ids"] = self._validate_integrations(
                kwargs["integration_ids"]
            )
        return self.store.edit(teammate_id, **kwargs)

    def add(
        self,
        teammate_id: str,
        *,
        scope: str = "project",
        name: str | None = None,
    ) -> dict[str, Any]:
        teammate = self.store.get(teammate_id)
        path = self.config_path(scope)
        installed = []
        prefix = name or f"teammate-{slugify(teammate['name'])}"
        for integration_id in teammate["integration_ids"]:
            entry = self.catalog.get(integration_id)
            server_name = f"{prefix}-{integration_id}"
            McpConfigStore.add(
                path,
                server_name,
                {
                    **entry.config,
                    "enabled": True,
                    "metadata": {
                        "teammate_id": teammate_id,
                        "teammate_name": teammate["name"],
                        "integration_id": integration_id,
                        "memory_enabled": teammate["memory_enabled"],
                        "privacy": teammate["privacy"],
                    },
                },
            )
            installed.append(server_name)
        return {
            "status": "PASS",
            "teammate_id": teammate_id,
            "scope": scope,
            "servers": installed,
            "config_path": str(path),
        }

    def status(self) -> dict[str, Any]:
        project = McpConfigStore.load(self.config_path("project"))
        global_config = McpConfigStore.load(self.config_path("global"))
        entries = []
        for scope, values in (("project", project), ("global", global_config)):
            for name, config in values.items():
                if not name.startswith("teammate-"):
                    continue
                entries.append(
                    {
                        "name": name,
                        "scope": scope,
                        "enabled": config.enabled,
                        "transport": config.transport,
                        "unresolved_env": list(config.unresolved_env),
                    }
                )
        return {
            "status": "PASS",
            "servers": sorted(entries, key=lambda item: (item["scope"], item["name"])),
            "count": len(entries),
        }

    def remove(
        self,
        *,
        teammate_id: str | None = None,
        server_name: str | None = None,
        scope: str = "project",
    ) -> dict[str, Any]:
        path = self.config_path(scope)
        configs = McpConfigStore.load(path)
        names = []
        if server_name:
            names = [server_name]
        elif teammate_id:
            teammate = self.store.get(teammate_id)
            prefix = f"teammate-{slugify(teammate['name'])}"
            names = [name for name in configs if name.startswith(prefix + "-")]
        else:
            raise ValueError("teammate_id or server_name is required")
        removed = [
            name for name in names if McpConfigStore.remove(path, name)
        ]
        return {
            "status": "PASS",
            "scope": scope,
            "removed": removed,
            "count": len(removed),
        }

    def list_config(self) -> dict[str, Any]:
        values = []
        for scope in ("project", "global"):
            path = self.config_path(scope)
            configs = McpConfigStore.load(path)
            for name, config in configs.items():
                if name.startswith("teammate-"):
                    values.append(
                        {
                            "scope": scope,
                            "path": str(path),
                            "name": name,
                            "transport": config.transport,
                            "enabled": config.enabled,
                            "url": config.url,
                            "command": list(config.command),
                            "unresolved_env": list(config.unresolved_env),
                        }
                    )
        return {
            "status": "PASS",
            "entries": sorted(values, key=lambda item: (item["scope"], item["name"])),
            "count": len(values),
        }

    def execute(self, operation: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if operation == "list":
            items = self.store.list()
            return {"status": "PASS", "teammates": items, "count": len(items)}
        if operation == "list-integrations":
            return self.list_integrations()
        if operation == "create":
            return {
                "status": "PASS",
                "teammate": self.create(
                    name=str(args.get("name") or ""),
                    description=args.get("description"),
                    integration_ids=args.get("integration_ids") or (),
                    memory_enabled=bool(args.get("memory_enabled", True)),
                    privacy=str(args.get("privacy") or "private"),
                    role=str(args.get("role") or "specialist"),
                    allowed_tools=args.get("allowed_tools") or (),
                    budgets=args.get("budgets") or {},
                    verification=args.get("verification") or (),
                    model=str(args.get("model") or "inherit"),
                    system_prompt=str(args.get("system_prompt") or ""),
                ),
            }
        if operation == "edit":
            teammate_id = str(args.get("datamate_id") or args.get("teammate_id") or "")
            if not teammate_id:
                raise ValueError("datamate_id/teammate_id is required")
            updates = {
                key: args[key]
                for key in (
                    "name",
                    "description",
                    "integration_ids",
                    "memory_enabled",
                    "privacy",
                    "role",
                    "allowed_tools",
                    "budgets",
                    "verification",
                    "model",
                    "system_prompt",
                )
                if key in args and args[key] is not None
            }
            return {"status": "PASS", "teammate": self.edit(teammate_id, **updates)}
        if operation == "delete":
            teammate_id = str(args.get("datamate_id") or args.get("teammate_id") or "")
            if not teammate_id:
                raise ValueError("datamate_id/teammate_id is required")
            return self.store.delete(teammate_id)
        if operation == "add":
            teammate_id = str(args.get("datamate_id") or args.get("teammate_id") or "")
            if not teammate_id:
                raise ValueError("datamate_id/teammate_id is required")
            return self.add(
                teammate_id,
                scope=str(args.get("scope") or "project"),
                name=args.get("name"),
            )
        if operation == "status":
            return self.status()
        if operation == "remove":
            return self.remove(
                teammate_id=args.get("datamate_id") or args.get("teammate_id"),
                server_name=args.get("server_name"),
                scope=str(args.get("scope") or "project"),
            )
        if operation == "list-config":
            return self.list_config()
        raise ValueError(f"unknown teammate operation: {operation}")
