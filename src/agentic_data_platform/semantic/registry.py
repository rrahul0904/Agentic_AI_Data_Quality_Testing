"""Provider-neutral semantic-layer registry for ADE."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import yaml


_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_resources (
  resource_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  provider TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(provider, name)
);
CREATE TABLE IF NOT EXISTS semantic_elements (
  resource_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  parent TEXT,
  description TEXT NOT NULL DEFAULT '',
  expression TEXT,
  data_type TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(resource_id, kind, name, parent)
);
CREATE TABLE IF NOT EXISTS semantic_relationships (
  resource_id TEXT NOT NULL,
  name TEXT NOT NULL,
  left_table TEXT,
  right_table TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(resource_id, name)
);
CREATE TABLE IF NOT EXISTS verified_queries (
  resource_id TEXT NOT NULL,
  name TEXT NOT NULL,
  question TEXT NOT NULL,
  sql TEXT NOT NULL,
  verified_by TEXT,
  verified_at TEXT,
  onboarding INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(resource_id, name)
);
"""


@dataclass(frozen=True)
class SemanticElement:
    kind: str
    name: str
    parent: str | None = None
    description: str = ""
    expression: str | None = None
    data_type: str | None = None
    metadata: dict[str, Any] | None = None


class SemanticRegistry:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    @staticmethod
    def _resource_id(provider: str, name: str) -> str:
        key = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{provider}:{name}").strip("-")
        return key.casefold()

    def upsert_resource(
        self,
        *,
        name: str,
        provider: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        resource_id = self._resource_id(provider, name)
        self.connection.execute(
            """
            INSERT INTO semantic_resources(resource_id,name,provider,description,metadata_json)
            VALUES(?,?,?,?,?)
            ON CONFLICT(resource_id) DO UPDATE SET
              description=excluded.description,
              metadata_json=excluded.metadata_json
            """,
            (resource_id, name, provider, description, json.dumps(metadata or {}, sort_keys=True, default=str)),
        )
        self.connection.commit()
        return resource_id

    def replace_contents(
        self,
        resource_id: str,
        *,
        elements: list[SemanticElement],
        relationships: list[dict[str, Any]],
        verified_queries: list[dict[str, Any]],
    ) -> None:
        self.connection.execute("DELETE FROM semantic_elements WHERE resource_id=?", (resource_id,))
        self.connection.execute("DELETE FROM semantic_relationships WHERE resource_id=?", (resource_id,))
        self.connection.execute("DELETE FROM verified_queries WHERE resource_id=?", (resource_id,))
        for item in elements:
            self.connection.execute(
                """
                INSERT INTO semantic_elements(
                  resource_id,kind,name,parent,description,expression,data_type,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    resource_id,
                    item.kind,
                    item.name,
                    item.parent,
                    item.description,
                    item.expression,
                    item.data_type,
                    json.dumps(item.metadata or {}, sort_keys=True, default=str),
                ),
            )
        for item in relationships:
            self.connection.execute(
                """
                INSERT INTO semantic_relationships(resource_id,name,left_table,right_table,metadata_json)
                VALUES(?,?,?,?,?)
                """,
                (
                    resource_id,
                    str(item["name"]),
                    item.get("left_table"),
                    item.get("right_table"),
                    json.dumps(item, sort_keys=True, default=str),
                ),
            )
        for item in verified_queries:
            self.connection.execute(
                """
                INSERT INTO verified_queries(
                  resource_id,name,question,sql,verified_by,verified_at,onboarding,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    resource_id,
                    str(item["name"]),
                    str(item["question"]),
                    str(item["sql"]),
                    item.get("verified_by"),
                    str(item.get("verified_at")) if item.get("verified_at") is not None else None,
                    int(bool(item.get("use_as_onboarding_question") or item.get("onboarding"))),
                    json.dumps(item, sort_keys=True, default=str),
                ),
            )
        self.connection.commit()

    def ingest_yaml(self, source: str | Path, *, provider: str = "snowflake-semantic-yaml") -> dict[str, Any]:
        path = Path(source).expanduser().resolve()
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError("semantic YAML must be an object")
        name = str(data.get("name") or path.stem)
        resource_id = self.upsert_resource(
            name=name,
            provider=provider,
            description=str(data.get("description") or ""),
            metadata={"source": str(path), "tags": data.get("tags") or []},
        )
        elements: list[SemanticElement] = []
        for table in data.get("tables") or []:
            table_name = str(table["name"])
            elements.append(SemanticElement(
                "table",
                table_name,
                description=str(table.get("description") or ""),
                metadata={
                    "base_table": table.get("base_table") or {},
                    "primary_key": table.get("primary_key"),
                    "unique_keys": table.get("unique_keys") or [],
                    "tags": table.get("tags") or [],
                },
            ))
            for key, kind in (
                ("dimensions", "dimension"),
                ("time_dimensions", "time_dimension"),
                ("facts", "fact"),
                ("metrics", "metric"),
                ("filters", "filter"),
            ):
                for item in table.get(key) or []:
                    elements.append(SemanticElement(
                        kind,
                        str(item["name"]),
                        parent=table_name,
                        description=str(item.get("description") or ""),
                        expression=item.get("expr"),
                        data_type=item.get("data_type"),
                        metadata={k: v for k, v in item.items() if k not in {"name", "description", "expr", "data_type"}},
                    ))
        for item in data.get("metrics") or []:
            elements.append(SemanticElement(
                "derived_metric",
                str(item["name"]),
                description=str(item.get("description") or ""),
                expression=item.get("expr"),
                metadata={k: v for k, v in item.items() if k not in {"name", "description", "expr"}},
            ))
        for item in data.get("variables") or []:
            elements.append(SemanticElement(
                "variable",
                str(item["name"]),
                description=str(item.get("description") or ""),
                data_type=item.get("data_type"),
                metadata={"default_value": item.get("default_value")},
            ))
        self.replace_contents(
            resource_id,
            elements=elements,
            relationships=list(data.get("relationships") or []),
            verified_queries=list(data.get("verified_queries") or []),
        )
        return self.show(resource_id)

    def ingest_describe_rows(
        self,
        name: str,
        rows: list[dict[str, Any]],
        *,
        provider: str = "snowflake-semantic-view",
    ) -> dict[str, Any]:
        grouped: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        view_metadata: dict[str, Any] = {}
        for raw in rows:
            row = {str(k).casefold(): v for k, v in raw.items()}
            kind = str(row.get("object_kind") or "").upper()
            object_name = row.get("object_name")
            parent = row.get("parent_entity")
            prop = str(row.get("property") or "").casefold()
            value = row.get("property_value")
            if not kind:
                if prop:
                    view_metadata[prop] = value
                continue
            key = (kind, str(object_name or ""), str(parent) if parent is not None else None)
            grouped.setdefault(key, {})[prop] = value

        elements: list[SemanticElement] = []
        relationships: list[dict[str, Any]] = []
        verified: list[dict[str, Any]] = []
        for (kind, object_name, parent), props in grouped.items():
            if kind == "RELATIONSHIP":
                relationships.append({"name": object_name, **props})
                continue
            if kind == "AI_VERIFIED_QUERY":
                verified.append({
                    "name": object_name,
                    "question": props.get("question") or "",
                    "sql": props.get("sql") or "",
                    "verified_by": props.get("verified_by"),
                    "verified_at": props.get("verified_at"),
                    "onboarding": str(props.get("onboarding_question") or "").casefold() == "true",
                    **props,
                })
                continue
            if kind == "CUSTOM_INSTRUCTIONS":
                view_metadata.setdefault("custom_instructions", {}).update(props)
                continue
            elements.append(SemanticElement(
                kind.casefold(),
                object_name or kind.casefold(),
                parent=parent,
                description=str(props.get("comment") or props.get("description") or ""),
                expression=props.get("expression") or props.get("expr"),
                data_type=props.get("data_type"),
                metadata=props,
            ))

        resource_id = self.upsert_resource(
            name=name,
            provider=provider,
            description=str(view_metadata.get("comment") or ""),
            metadata=view_metadata,
        )
        self.replace_contents(resource_id, elements=elements, relationships=relationships, verified_queries=verified)
        return self.show(resource_id)

    def list(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM semantic_resources ORDER BY provider,name"
        ).fetchall()
        return [self._resource(row) for row in rows]

    def show(self, resource_id_or_name: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT * FROM semantic_resources
            WHERE resource_id=? OR name=?
            ORDER BY resource_id LIMIT 1
            """,
            (resource_id_or_name.casefold(), resource_id_or_name),
        ).fetchone()
        if row is None:
            raise KeyError(f"semantic resource not found: {resource_id_or_name}")
        resource = self._resource(row)
        resource_id = resource["resource_id"]
        resource["elements"] = [
            self._element(item) for item in self.connection.execute(
                "SELECT * FROM semantic_elements WHERE resource_id=? ORDER BY kind,parent,name",
                (resource_id,),
            ).fetchall()
        ]
        resource["relationships"] = [
            json.loads(item["metadata_json"]) for item in self.connection.execute(
                "SELECT * FROM semantic_relationships WHERE resource_id=? ORDER BY name",
                (resource_id,),
            ).fetchall()
        ]
        resource["verified_queries"] = [
            self._verified(item) for item in self.connection.execute(
                "SELECT * FROM verified_queries WHERE resource_id=? ORDER BY name",
                (resource_id,),
            ).fetchall()
        ]
        resource["counts"] = {
            "elements": len(resource["elements"]),
            "relationships": len(resource["relationships"]),
            "verified_queries": len(resource["verified_queries"]),
        }
        return resource

    def search(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        terms = [term.casefold() for term in re.findall(r"[A-Za-z0-9_.$-]+", query) if len(term) > 1]
        results: list[dict[str, Any]] = []
        for resource in self.list():
            full = self.show(resource["resource_id"])
            for item in full["elements"]:
                haystack = " ".join([
                    item["name"],
                    item.get("parent") or "",
                    item.get("description") or "",
                    item.get("expression") or "",
                    json.dumps(item.get("metadata") or {}, default=str),
                ]).casefold()
                score = sum(haystack.count(term) for term in terms)
                if score:
                    results.append({
                        "score": score,
                        "resource_id": full["resource_id"],
                        "resource_name": full["name"],
                        **item,
                    })
        return sorted(results, key=lambda item: (-item["score"], item["resource_name"], item["name"]))[:limit]

    def find_verified(self, question: str, *, limit: int = 10) -> list[dict[str, Any]]:
        terms = {term.casefold() for term in re.findall(r"[A-Za-z0-9_]+", question) if len(term) > 2}
        rows = self.connection.execute(
            """
            SELECT q.*, r.name AS resource_name, r.provider
            FROM verified_queries q JOIN semantic_resources r USING(resource_id)
            """
        ).fetchall()
        ranked = []
        for row in rows:
            words = {term.casefold() for term in re.findall(r"[A-Za-z0-9_]+", str(row["question"])) if len(term) > 2}
            overlap = len(terms.intersection(words))
            if overlap:
                item = self._verified(row)
                item.update({"resource_name": row["resource_name"], "provider": row["provider"], "score": overlap})
                ranked.append(item)
        return sorted(ranked, key=lambda item: (-item["score"], item["resource_name"], item["name"]))[:limit]

    @staticmethod
    def _resource(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "resource_id": row["resource_id"],
            "name": row["name"],
            "provider": row["provider"],
            "description": row["description"],
            "metadata": json.loads(row["metadata_json"]),
        }

    @staticmethod
    def _element(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "kind": row["kind"],
            "name": row["name"],
            "parent": row["parent"],
            "description": row["description"],
            "expression": row["expression"],
            "data_type": row["data_type"],
            "metadata": json.loads(row["metadata_json"]),
        }

    @staticmethod
    def _verified(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "resource_id": row["resource_id"],
            "name": row["name"],
            "question": row["question"],
            "sql": row["sql"],
            "verified_by": row["verified_by"],
            "verified_at": row["verified_at"],
            "onboarding": bool(row["onboarding"]),
            "metadata": json.loads(row["metadata_json"]),
        }
