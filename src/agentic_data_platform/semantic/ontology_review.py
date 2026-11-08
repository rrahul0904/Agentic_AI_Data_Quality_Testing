"""Fail-closed ontology review overlay for the existing SemanticRegistry.

This is a local/offline certification *record*, not an identity/authentication system,
SQL generator, live warehouse profiler, or an approval to deploy. It never executes SQL.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ontology_review_receipts (
    resource_id TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    object_name TEXT NOT NULL,
    parent_name TEXT NOT NULL DEFAULT '',
    definition_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (resource_id, object_kind, object_name, parent_name)
);
"""
_KINDS = {"table", "dimension", "time_dimension", "fact", "metric", "derived_metric", "filter", "relationship"}


def _digest(value: Any) -> str:
    packed = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def schema_fingerprint(columns: Sequence[Mapping[str, Any]]) -> str:
    """Fingerprint an independently supplied source-column inventory; no database access.

    Callers must supply fresh metadata (and versioned semantic evidence when available).
    Equal metadata fingerprints do NOT prove that the business meaning is unchanged.
    """
    if not columns:
        raise ValueError("a nonempty independently captured schema inventory is required")
    normalized = []
    for entry in columns:
        table = str(entry.get("table") or "").strip()
        column = str(entry.get("column") or "").strip()
        data_type = str(entry.get("data_type") or "").strip()
        if not table or not column or not data_type:
            raise ValueError("each schema entry needs table, column and data_type")
        normalized.append({str(k): v for k, v in sorted(entry.items())})
    return _digest(sorted(normalized, key=lambda x: (str(x["table"]).casefold(), str(x["column"]).casefold())))


def draft_term_candidates(columns: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Make explicitly unverified naming proposals without guessing business measures."""
    proposals = []
    for entry in columns:
        table, column = str(entry.get("table") or "").strip(), str(entry.get("column") or "").strip()
        if not table or not column:
            raise ValueError("term candidate needs table and column")
        name = re.sub(r"[_\W]+", " ", column).strip().lower()
        proposals.append({"term": name, "table": table, "column": column,
                          "status": "HYPOTHESIS", "requires_review": "true"})
    return proposals


class OntologyReviewLedger:
    """Review receipts tied to both a registry definition and a source fingerprint."""

    def __init__(self, registry: Any, connection: sqlite3.Connection | None = None) -> None:
        self.registry = registry
        self.connection = connection if connection is not None else registry.connection
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def _object(self, resource_id: str, kind: str, name: str, parent: str | None = None) -> dict[str, Any]:
        if kind not in _KINDS:
            raise ValueError(f"unsupported ontology object kind: {kind}")
        resource = self.registry.show(resource_id)
        objects = resource["relationships"] if kind == "relationship" else resource["elements"]
        matches = [obj for obj in objects if obj.get("name") == name and
                   (kind == "relationship" or (obj.get("kind") == kind and (obj.get("parent") or "") == (parent or "")))]
        if len(matches) != 1:
            raise KeyError(f"ontology object not uniquely found: {kind}:{parent or ''}:{name}")
        return matches[0]

    def record_review(self, resource_id: str, *, kind: str, name: str, reviewer: str,
                      evidence_ref: str, source_sha256: str, parent: str | None = None) -> dict[str, str]:
        """Record an explicit review decision; caller is responsible for reviewer authentication.

        Metadata-derived or agent-generated proposals must NOT call this automatically.
        """
        if not reviewer.strip() or not evidence_ref.strip():
            raise ValueError("reviewer and traceable evidence_ref are required")
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("source_sha256 must be a fresh 64-character lowercase SHA-256 fingerprint")
        obj = self._object(resource_id, kind, name, parent)
        definition_hash = _digest(obj)
        reviewed_at = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO ontology_review_receipts
            (resource_id, object_kind, object_name, parent_name, definition_sha256,
             source_sha256, reviewer, evidence_ref, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(resource_id, object_kind, object_name, parent_name)
            DO UPDATE SET definition_sha256=excluded.definition_sha256,
              source_sha256=excluded.source_sha256, reviewer=excluded.reviewer,
              evidence_ref=excluded.evidence_ref, reviewed_at=excluded.reviewed_at""",
            (resource_id, kind, name, parent or "", definition_hash, source_sha256,
             reviewer.strip(), evidence_ref.strip(), reviewed_at),
        )
        self.connection.commit()
        return {"status": "REVIEW_RECORDED", "kind": kind, "name": name,
                "definition_sha256": definition_hash, "source_sha256": source_sha256,
                "reviewed_at": reviewed_at}

    def review_status(self, resource_id: str, *, kind: str, name: str,
                      current_source_sha256: str, parent: str | None = None) -> str:
        obj = self._object(resource_id, kind, name, parent)
        row = self.connection.execute(
            """SELECT definition_sha256, source_sha256 FROM ontology_review_receipts
               WHERE resource_id=? AND object_kind=? AND object_name=? AND parent_name=?""",
            (resource_id, kind, name, parent or ""),
        ).fetchone()
        if row is None:
            return "UNREVIEWED"
        if row[0] != _digest(obj) or row[1] != current_source_sha256:
            return "STALE"
        return "REVIEW_RECORDED"

    def gate(self, resource_id: str, *, requested_concepts: Sequence[str],
             current_source_sha256: str, required_relationships: Sequence[str] = ()) -> dict[str, Any]:
        """Fail closed: caller supplies extracted concepts; this is NOT a text-to-SQL parser.

        A READY result permits only the *next* protected SQL generation/validation stage.
        It does not approve a query, authorize access, or execute any SQL.
        """
        resource = self.registry.show(resource_id)
        if not requested_concepts or not re.fullmatch(r"[0-9a-f]{64}", current_source_sha256):
            return {"status": "BLOCKED", "reason": "MISSING_CONCEPTS_OR_FRESH_SCHEMA_EVIDENCE"}
        selected = []
        for concept in requested_concepts:
            needle = str(concept).strip().casefold()
            if not needle:
                return {"status": "BLOCKED", "reason": "EMPTY_CONCEPT"}
            matches = []
            for element in resource["elements"]:
                if element["kind"] not in _KINDS or element["kind"] == "table":
                    continue
                synonyms = element.get("metadata", {}).get("synonyms") or []
                if isinstance(synonyms, str):
                    synonyms = [synonyms]
                aliases = [element["name"], *synonyms]
                if needle in {str(alias).casefold() for alias in aliases}:
                    matches.append(element)
            if len(matches) != 1:
                return {"status": "BLOCKED", "reason": "UNKNOWN_CONCEPT" if not matches else "AMBIGUOUS_CONCEPT",
                        "concept": concept}
            element = matches[0]
            status = self.review_status(resource_id, kind=element["kind"], name=element["name"],
                                        parent=element.get("parent"), current_source_sha256=current_source_sha256)
            if status != "REVIEW_RECORDED":
                return {"status": "BLOCKED", "reason": status, "concept": concept}
            selected.append({"kind": element["kind"], "name": element["name"],
                             "parent": element.get("parent")})
        parents = {item["parent"] for item in selected if item["parent"]}
        if len(parents) > 1 and not required_relationships:
            return {"status": "BLOCKED", "reason": "JOIN_PATH_NOT_DECLARED"}
        reviewed_edges = []
        for relationship in required_relationships:
            try:
                state = self.review_status(resource_id, kind="relationship", name=relationship,
                                           current_source_sha256=current_source_sha256)
            except KeyError:
                return {"status": "BLOCKED", "reason": "UNKNOWN_RELATIONSHIP", "relationship": relationship}
            if state != "REVIEW_RECORDED":
                return {"status": "BLOCKED", "reason": state, "relationship": relationship}
            edge = self._object(resource_id, "relationship", relationship)
            left, right = str(edge.get("left_table") or ""), str(edge.get("right_table") or "")
            if not left or not right:
                return {"status": "BLOCKED", "reason": "JOIN_ENDPOINTS_NOT_VERIFIED", "relationship": relationship}
            reviewed_edges.append((left, right))
        if len(parents) > 1:
            connected = {next(iter(parents))}
            for _ in range(len(reviewed_edges)):
                for left, right in reviewed_edges:
                    if left in connected:
                        connected.add(right)
                    if right in connected:
                        connected.add(left)
            if not parents <= connected:
                return {"status": "BLOCKED", "reason": "UNCONNECTED_JOIN_PATH"}
        return {"status": "READY_FOR_SQL_VALIDATION", "resolved_concepts": selected,
                "reviewed_relationships": list(required_relationships),
                "source_sha256": current_source_sha256}
